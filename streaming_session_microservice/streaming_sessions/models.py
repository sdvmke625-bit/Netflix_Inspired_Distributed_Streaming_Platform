from django.db import models
from django.contrib.auth.models import User


class Session(models.Model):
    STATUS_CHOICES = [
        ("playing", "Playing"),
        ("paused", "Paused"),
        ("ended", "Ended"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="streaming_sessions",
    )

    movie_id = models.IntegerField()
    movie_duration = models.PositiveIntegerField()
    playback_position = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="playing",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Session {self.id} - Movie {self.movie_id} Duration : {self.movie_duration} Playback Position : {self.playback_position} Status : {self.status} Started at : {self.started_at} Updated at : {self.updated_at}\n"