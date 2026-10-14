from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from .models import Session

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "password"]
        read_only_fields = ["id"]
        extra_kwargs = {
            "password": {"write_only": True}
        }

    def validate_username(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(
                "Username cannot be empty."
            )
        return value

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return value

    def create(self, validated_data):
        user = User(
            username=validated_data["username"]
        )
        user.set_password(validated_data["password"])
        user.save()
        return user

class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Session
        fields = [
            "id",
            "user",
            "movie_duration",
            "movie_id",
            "playback_position",
            "status",
            "version",
            "started_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "movie_duration",
            "version",
            "started_at",
            "updated_at",
        ]

    def validate_playback_position(self, value):
        if value < 0:
            raise serializers.ValidationError(
                "Playback position cannot be negative."
            )
        return value

    def validate_movie_id(self, value):
        if self.instance is not None:
            if value != self.instance.movie_id:
                raise serializers.ValidationError(
                    "Movie cannot be changed for an existing session."
                )
        return value

    def validate_status(self, value):
        if self.instance is None:
            return value

        current_status = self.instance.status

        allowed_transitions = {
            "playing": {"playing", "paused", "ended"},
            "paused": {"paused", "playing", "ended"},
            "ended": {"ended"},
        }

        if value not in allowed_transitions[current_status]:
            raise serializers.ValidationError(
                f"Cannot change session status from "
                f"{current_status} to {value}."
            )

        return value

    def validate(self, attrs):
        if self.instance is not None and self.instance.status == "ended":
            raise serializers.ValidationError(
                "Completed sessions cannot be updated."
            )

        if self.instance is None:
            movie_duration = self.context.get("movie_duration")
            playback_position = attrs.get("playback_position", 0)
            status = attrs.get("status", "playing")
        else:
            movie_duration = self.instance.movie_duration
            playback_position = attrs.get(
                "playback_position",
                self.instance.playback_position,
            )

        if playback_position > movie_duration:
            raise serializers.ValidationError(
                {
                    "playback_position": (
                        "Playback position cannot be greater than "
                        "the movie duration."
                    )
                }
            )

        if playback_position == movie_duration:
            attrs["status"] = "ended"

        return attrs
