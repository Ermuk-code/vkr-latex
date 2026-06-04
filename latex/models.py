from django.db import models
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import Avg

class Category(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name
class Item(models.Model):

    STATUS_CHOICES = (
        ('pending', 'На модерации'),
        ('available', 'Опубликовано'),
        ('unavailable', 'Недоступно'),
        ('blocked', 'Заблокировано'),
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='items'
    )

    title = models.CharField(max_length=255)
    description = models.TextField()
    price_per_day = models.DecimalField(max_digits=10, decimal_places=2)
    deposit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='Залог'
    )
    average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0
    )

    reviews_count = models.IntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='available'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    category = models.ForeignKey(
    Category,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name='items'
    )
    def __str__(self):
        return self.title


class ItemImage(models.Model):
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='images'
    )
    image = models.ImageField(upload_to='items/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image for {self.item.title}"

    class Meta:
        ordering = ['-uploaded_at']


class ItemModerationRequest(models.Model):
    ACTION_CREATE = 'create'
    ACTION_UPDATE = 'update'
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'

    ACTION_CHOICES = (
        (ACTION_CREATE, 'Создание'),
        (ACTION_UPDATE, 'Редактирование'),
    )
    STATUS_CHOICES = (
        (STATUS_PENDING, 'Ожидает рассмотрения'),
        (STATUS_APPROVED, 'Одобрена'),
        (STATUS_REJECTED, 'Отклонена'),
    )

    item = models.ForeignKey(
        Item,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='moderation_requests',
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='item_moderation_requests',
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    item_snapshot = models.JSONField(default=dict, blank=True)
    user_snapshot = models.JSONField(default=dict, blank=True)
    rejection_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_item_moderation_requests',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['submitted_by', '-created_at']),
            models.Index(fields=['item', 'status']),
        ]

    def __str__(self):
        return f'{self.get_action_display()} объявления {self.item}'


class ItemVideo(models.Model):
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='videos'
    )
    video = models.FileField(upload_to='items/videos/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Video for {self.item.title}"

    class Meta:
        ordering = ['-uploaded_at']


class ItemReview(models.Model):
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='reviews',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='item_reviews',
    )
    rating = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(5)],
    )
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['item', '-created_at']),
            models.Index(fields=['author', '-created_at']),
        ]

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            self.update_item_rating_counters(item=self.item)

    def delete(self, *args, **kwargs):
        item = self.item
        super().delete(*args, **kwargs)
        self.update_item_rating_counters(item=item)

    @staticmethod
    def update_item_rating_counters(*, item=None):
        if item is None:
            return
        qs = ItemReview.objects.filter(item=item)
        item.average_rating = qs.aggregate(avg=Avg('rating'))['avg'] or 0
        item.reviews_count = qs.count()
        item.save(update_fields=['average_rating', 'reviews_count'])
