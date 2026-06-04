from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser, IsAuthenticatedOrReadOnly, IsAuthenticated
from users.permissions import IsProfileCompleted
from .models import Item, ItemModerationRequest, ItemReview
from .permissions import IsOwner
from .serializers import ItemModerationRequestSerializer, ItemSerializer, ItemReviewSerializer
from rest_framework.decorators import action
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db import models
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from users.permissions import IsProfileCompleted

from .models import Category, Item, ItemImage
from .permissions import IsOwner
from .serializers import CategorySerializer, ItemImageSerializer, ItemSerializer
from .services import (
    approve_item_moderation_request,
    create_item_moderation_request,
    reject_item_moderation_request,
)

class CategoryViewSet(ModelViewSet):
    queryset = Category.objects.order_by('name')
    serializer_class = CategorySerializer


class IsSuperUser(IsAdminUser):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class ItemModerationRequestViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ItemModerationRequestSerializer
    permission_classes = [IsSuperUser]

    def get_queryset(self):
        queryset = ItemModerationRequest.objects.select_related(
            'item',
            'item__owner',
            'item__category',
            'submitted_by',
            'reviewed_by',
        ).prefetch_related('item__images', 'item__videos')

        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)

        return queryset

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        moderation_request = self.get_object()
        if moderation_request.status != ItemModerationRequest.STATUS_PENDING:
            raise ValidationError({'status': ['Заявка уже рассмотрена.']})

        approve_item_moderation_request(moderation_request, request.user)
        return Response(self.get_serializer(moderation_request).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        moderation_request = self.get_object()
        if moderation_request.status != ItemModerationRequest.STATUS_PENDING:
            raise ValidationError({'status': ['Заявка уже рассмотрена.']})

        reason = (request.data.get('reason') or '').strip()
        if not reason:
            raise ValidationError({'reason': ['Укажите причину отказа.']})

        serialized = self.get_serializer(moderation_request).data
        reject_item_moderation_request(moderation_request, request.user, reason)
        serialized['status'] = ItemModerationRequest.STATUS_REJECTED
        serialized['rejection_reason'] = reason
        return Response(serialized)


class ItemViewSet(viewsets.ModelViewSet):

    serializer_class = ItemSerializer

    def get_queryset(self):

        user = self.request.user

        if user.is_authenticated:
            queryset = Item.objects.filter(
                models.Q(status='available') | models.Q(owner=user)
            )
        else:
            queryset = Item.objects.filter(status='available')

        min_rating = self.request.query_params.get('min_rating')
        mine = self.request.query_params.get('mine')

        if mine in ['1', 'true', 'True'] and user.is_authenticated:
            queryset = queryset.filter(owner=user)

        if min_rating:
            queryset = queryset.filter(average_rating__gte=min_rating)

        return queryset.select_related('owner', 'category').distinct()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]

    filterset_fields = ['status', 'category']
    search_fields = ['title', 'description']
    ordering_fields = ['price_per_day', 'created_at', 'average_rating']
    ordering = ['-created_at']

    def perform_create(self, serializer):
        item = serializer.save(owner=self.request.user, status='pending')
        create_item_moderation_request(
            item=item,
            submitted_by=self.request.user,
            action=ItemModerationRequest.ACTION_CREATE,
        )

    def perform_update(self, serializer):
        item = serializer.save(owner=self.request.user, status='pending')
        create_item_moderation_request(
            item=item,
            submitted_by=self.request.user,
            action=ItemModerationRequest.ACTION_UPDATE,
        )

    def get_permissions(self):
        if self.action in ['update', 'partial_update', 'destroy']:
            return [IsOwner(), IsProfileCompleted()]
        if self.action == 'create':
            return [IsAuthenticatedOrReadOnly(), IsProfileCompleted()]
        return []

    @action(detail=True, methods=['get'])
    def booked_ranges(self, request, pk=None):
        item = self.get_object()
        active_bookings = item.bookings.filter(status__in=['pending', 'confirmed']).order_by('start_date')
        return Response(
            [
                {
                    'start_date': booking.start_date.isoformat(),
                    'end_date': booking.end_date.isoformat(),
                }
                for booking in active_bookings
            ]
        )

    @action(detail=True, methods=['get', 'post'], permission_classes=[IsAuthenticatedOrReadOnly])
    def reviews(self, request, pk=None):
        item = self.get_object()

        if request.method.lower() == 'get':
            qs = ItemReview.objects.filter(item=item).select_related('author').order_by('-created_at')
            page = self.paginate_queryset(qs)
            serializer = ItemReviewSerializer(page if page is not None else qs, many=True)
            if page is not None:
                return self.get_paginated_response(serializer.data)
            return Response(serializer.data)

        # POST
        if not request.user.is_authenticated:
            raise PermissionDenied("Войдите в систему.")
        if item.owner_id == request.user.id:
            raise PermissionDenied("Нельзя оставить отзыв на своё объявление.")

        serializer = ItemReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review = ItemReview.objects.create(
            item=item,
            author=request.user,
            rating=serializer.validated_data['rating'],
            comment=serializer.validated_data.get('comment', ''),
        )
        return Response(ItemReviewSerializer(review).data, status=201)

class ItemImageUploadView(generics.CreateAPIView):
    serializer_class = ItemImageSerializer
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        item_id = self.request.data.get('item')
        if not item_id:
            raise ValidationError({'item': ['Укажите объявление.']})

        try:
            item = Item.objects.get(id=item_id)
        except Item.DoesNotExist:
            raise ValidationError({'item': ['Объявление не найдено.']})

        if item.owner != self.request.user:
            raise PermissionDenied("Это действие доступно только владельцу объявления.")

        serializer.save(item=item)


class ItemImageDeleteView(generics.DestroyAPIView):
    serializer_class = ItemImageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ItemImage.objects.filter(item__owner=self.request.user)
