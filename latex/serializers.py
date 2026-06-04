from decimal import Decimal, ROUND_HALF_UP
from rest_framework import serializers

from .models import Category, Item, ItemImage, ItemModerationRequest, ItemReview, ItemVideo

MARKUP_RATE = Decimal('0.20')  # 20% наценка платформы


class ItemImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemImage
        fields = ['id', 'image']


class ItemVideoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemVideo
        fields = ['id', 'video']


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name']

class ItemSerializer(serializers.ModelSerializer):
    images = ItemImageSerializer(many=True, read_only=True)
    videos = ItemVideoSerializer(many=True, read_only=True)
    booked_ranges = serializers.SerializerMethodField()
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    item_reviews = serializers.SerializerMethodField()
    owner_rating = serializers.DecimalField(
        source='owner.average_rating',
        max_digits=3,
        decimal_places=2,
        read_only=True
    )
    owner_reviews_count = serializers.IntegerField(
        source='owner.reviews_count',
        read_only=True
    )
    # Цена с наценкой 20% (для арендатора)
    price_with_markup = serializers.SerializerMethodField()
    markup_rate = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = '__all__'
        read_only_fields = ['owner', 'average_rating', 'reviews_count', 'created_at']

    def get_price_with_markup(self, obj):
        """Цена для арендатора с наценкой 20% платформы."""
        price = Decimal(str(obj.price_per_day))
        price_with_markup = (price * (1 + MARKUP_RATE)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return str(price_with_markup)

    def get_markup_rate(self, obj):
        """Процент наценки платформы (20%)."""
        return str(MARKUP_RATE * 100)

    def get_booked_ranges(self, obj):
        active_bookings = obj.bookings.filter(status__in=['pending', 'confirmed']).order_by('start_date')
        return [
            {
                'start_date': booking.start_date.isoformat(),
                'end_date': booking.end_date.isoformat(),
            }
            for booking in active_bookings
        ]

    def get_item_reviews(self, obj):
        from bookings.models import Review

        reviews = Review.objects.filter(
            booking__item=obj
        ).filter(
            is_hidden=False
        ).select_related('booking__renter').order_by('-created_at')[:6]

        return [
            {
                'id': review.id,
                'rating': review.rating,
                'comment': review.comment,
                'created_at': review.created_at.isoformat(),
                'author_username': review.booking.renter.username,
            }
            for review in reviews
        ]


class ModerationUserSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    phone = serializers.CharField(read_only=True)
    user_type = serializers.CharField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    entrepreneur_name = serializers.CharField(read_only=True)
    company_name = serializers.CharField(read_only=True)
    passport_series = serializers.CharField(read_only=True)
    passport_number = serializers.CharField(read_only=True)
    inn = serializers.CharField(read_only=True)
    kpp = serializers.CharField(read_only=True)
    ogrnip = serializers.CharField(read_only=True)
    profile_completed = serializers.BooleanField(read_only=True)


class ItemModerationRequestSerializer(serializers.ModelSerializer):
    item = ItemSerializer(read_only=True)
    submitted_by = ModerationUserSerializer(read_only=True)
    reviewed_by_username = serializers.CharField(source='reviewed_by.username', read_only=True)

    class Meta:
        model = ItemModerationRequest
        fields = [
            'id',
            'item',
            'submitted_by',
            'action',
            'status',
            'item_snapshot',
            'user_snapshot',
            'rejection_reason',
            'reviewed_by',
            'reviewed_by_username',
            'reviewed_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class ItemReviewSerializer(serializers.ModelSerializer):
    author_username = serializers.CharField(source='author.username', read_only=True)

    class Meta:
        model = ItemReview
        fields = ['id', 'item', 'author', 'author_username', 'rating', 'comment', 'created_at']
        read_only_fields = ['id', 'item', 'author', 'author_username', 'created_at']
