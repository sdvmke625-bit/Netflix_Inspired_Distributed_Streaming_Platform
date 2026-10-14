from django.db import models


class Movie(models.Model):
    title = models.CharField(max_length=200, unique=True)
    description = models.TextField()
    genre = models.CharField(max_length=100)
    # Duration is stored in seconds for consistent playback semantics.
    duration = models.PositiveIntegerField()
    release_date = models.DateField()
    # Relative frontend path, for example /videos/movie.mp4
    video_url = models.CharField(max_length=500)
    def __str__(self):
        return self.title