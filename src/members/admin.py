""" Configuration of Members models for the admin interface.
"""

from django import forms
from django.contrib import admin, messages
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.utils import timezone
from image_cropping import ImageCroppingMixin
from core.models import ShirtNumberStatus
from members.models import (
    Member, CommitteeMembership, CommitteePosition, SquadMembership,
    ShirtNumber, ShirtNumberAssignment,
)


class SquadMembershipInline(admin.TabularInline):
    """ Allows squad membership to be edited from the admin page of the member model."""
    model = SquadMembership
    extra = 0


def _active_assignment_q(today):
    return Q(end_date__isnull=True) | Q(end_date__gte=today)


class _ExistingRowReadonlyFormMixin:
    """ Form behaviour shared by both inline forms below.

        For **regular staff**:
          - New rows (no PK yet) are fully editable.
          - On every existing row (PK set), the FK field (shirt/member) is
            disabled — switching which shirt a member holds, or which member
            holds a shirt, is a *new assignment* and should go via "Add
            another".
          - On historic rows (end_date in the past) the date fields are
            disabled as well, so the row is fully readonly.
          - The FK's queryset is narrowed to just the row's own value on
            existing rows so the disabled <select> renders the correct
            selected option.

        For **superusers**:
          - All of the above restrictions are skipped. Every field on every
            row is editable, so superusers can fix broken data without
            fighting the form. Model-level `clean()` rules still apply.

        The request is injected onto the form class in get_formset() via a
        dynamic subclass; see each inline's get_formset.
    """
    _request = None    # set per-request in the inline's get_formset
    fk_field_name = ''  # set by subclass: 'shirt' or 'member'
    fk_value_attr = ''  # set by subclass: 'shirt_id' or 'member_id'
    fk_model = None     # set by subclass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self._is_superuser():
            return
        today = timezone.now().date()
        inst = self.instance
        if not (inst and inst.pk):
            return  # New row — leave everything editable.
        # Existing row: FK is readonly regardless of active/historic.
        fk_value = getattr(inst, self.fk_value_attr, None)
        if self.fk_field_name in self.fields:
            self.fields[self.fk_field_name].disabled = True
            if fk_value and self.fk_model is not None:
                self.fields[self.fk_field_name].queryset = (
                    self.fk_model.objects.filter(pk=fk_value)
                )
        # Historic row: date fields are readonly too.
        is_historic = inst.end_date is not None and inst.end_date < today
        if is_historic:
            for name, field in self.fields.items():
                field.disabled = True

    def _is_superuser(self):
        req = self._request
        user = getattr(req, 'user', None) if req else None
        return bool(user and user.is_superuser)


def _inject_request_into_form(form_cls, request):
    """ Return a dynamic subclass of `form_cls` with `_request` bound to this
        request. A new subclass per request keeps the binding thread-safe
        without mutating the shared form class.
    """
    return type(form_cls.__name__, (form_cls,), {'_request': request})


class MemberShirtAssignmentInlineForm(_ExistingRowReadonlyFormMixin, forms.ModelForm):
    fk_field_name = 'shirt'
    fk_value_attr = 'shirt_id'
    fk_model = ShirtNumber

    class Meta:
        model = ShirtNumberAssignment
        fields = ('shirt', 'start_date', 'end_date')


class ShirtAssignmentInlineForm(_ExistingRowReadonlyFormMixin, forms.ModelForm):
    fk_field_name = 'member'
    fk_value_attr = 'member_id'
    fk_model = Member

    class Meta:
        model = ShirtNumberAssignment
        fields = ('member', 'start_date', 'end_date')


class MemberShirtAssignmentInline(admin.TabularInline):
    """ A member's full shirt history, edited from the Member admin page.

        One inline, mixed-mode rows handled by MemberShirtAssignmentInlineForm:
          - New rows are fully editable.
          - Existing active rows have the shirt FK disabled; dates stay editable
            so admins can end the row by setting end_date. Superusers see
            everything editable.
          - Historic rows are fully disabled (except for superusers).

        The shirt FK dropdown on new/editable rows is limited to Available
        shirts of the member's gender, plus the member's currently-held shirt
        so the active row's dropdown round-trips cleanly. Shirts the member
        *used* to hold are not offered. Superusers see all shirts of the
        member's gender.
    """
    model = ShirtNumberAssignment
    form = MemberShirtAssignmentInlineForm
    extra = 0
    fields = ('shirt', 'start_date', 'end_date')
    ordering = ('-start_date',)
    verbose_name_plural = 'Shirt number assignments'

    def get_formset(self, request, obj=None, **kwargs):
        kwargs['form'] = _inject_request_into_form(
            kwargs.get('form', self.form), request)
        return super().get_formset(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'shirt':
            today = timezone.now().date()
            member_id = request.resolver_match.kwargs.get('object_id')
            if request.user.is_superuser:
                # Superusers see every shirt (optionally filtered to the
                # member's gender). No "only Available" / "only held by this
                # member" narrowing — superusers can pick any shirt to
                # correct bad data.
                if member_id:
                    try:
                        member = Member.objects.get(pk=member_id)
                        qs = ShirtNumber.objects.filter(gender=member.gender)
                    except Member.DoesNotExist:
                        qs = ShirtNumber.objects.all()
                else:
                    qs = ShirtNumber.objects.all()
            elif member_id:
                try:
                    member = Member.objects.get(pk=member_id)
                    held_ids = ShirtNumberAssignment.objects.filter(
                        member_id=member_id,
                    ).filter(_active_assignment_q(today)).values('shirt_id')
                    available = ShirtNumber.objects.filter(
                        status=ShirtNumberStatus.Available,
                        gender=member.gender,
                    )
                    held = ShirtNumber.objects.filter(pk__in=held_ids)
                    qs = (available | held).distinct()
                except Member.DoesNotExist:
                    qs = ShirtNumber.objects.filter(status=ShirtNumberStatus.Available)
            else:
                qs = ShirtNumber.objects.filter(status=ShirtNumberStatus.Available)
            kwargs['queryset'] = qs.order_by('gender', 'number')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class ShirtAssignmentInline(admin.TabularInline):
    """ A shirt's full assignment history, edited from the ShirtNumber admin.

        Mirrors MemberShirtAssignmentInline on the inverse relation: the
        member FK is editable only on new rows (regular staff), and on all
        rows for superusers. Member dropdown narrowing filters out members
        who already hold a shirt (except superusers).
    """
    model = ShirtNumberAssignment
    form = ShirtAssignmentInlineForm
    extra = 0
    fields = ('member', 'start_date', 'end_date')
    ordering = ('-start_date',)
    verbose_name_plural = 'Assignments'

    def get_formset(self, request, obj=None, **kwargs):
        kwargs['form'] = _inject_request_into_form(
            kwargs.get('form', self.form), request)
        return super().get_formset(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'member':
            today = timezone.now().date()
            shirt_id = request.resolver_match.kwargs.get('object_id')
            if request.user.is_superuser:
                # Superusers can pick any member (optionally filtered to the
                # shirt's gender). No "current only" / "shirtless only" narrowing.
                if shirt_id:
                    try:
                        shirt = ShirtNumber.objects.get(pk=shirt_id)
                        qs = Member.objects.filter(gender=shirt.gender)
                    except ShirtNumber.DoesNotExist:
                        qs = Member.objects.all()
                else:
                    qs = Member.objects.all()
            else:
                busy_ids = ShirtNumberAssignment.objects.filter(
                    _active_assignment_q(today)
                ).values_list('member_id', flat=True)
                qs = Member.objects.filter(is_current=True).exclude(pk__in=busy_ids)
                if shirt_id:
                    try:
                        shirt = ShirtNumber.objects.get(pk=shirt_id)
                        qs = qs.filter(gender=shirt.gender)
                        held_ids = ShirtNumberAssignment.objects.filter(
                            shirt_id=shirt_id,
                        ).filter(_active_assignment_q(today)).values('member_id')
                        held = Member.objects.filter(pk__in=held_ids)
                        qs = (qs | held).distinct()
                    except ShirtNumber.DoesNotExist:
                        pass
            kwargs['queryset'] = qs.order_by('first_name', 'last_name')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Member)
class MemberAdmin(ImageCroppingMixin, admin.ModelAdmin):
    """ Admin interface definition for the Member model."""
    model = Member
    inlines = (SquadMembershipInline, MemberShirtAssignmentInline)
    search_fields = ('first_name', 'known_as', 'last_name',
                     '=shirt_assignments__shirt__number')
    list_filter = ('is_current', 'gender', 'pref_position',
                   'is_umpire', 'is_coach')
    list_display = ('full_name_with_option', 'user', 'gender', 'pref_position',
                    'current_shirt_display', 'is_current', 'is_umpire', 'is_coach')
    fieldsets = [
        ('Personal', {'fields': ['user', 'first_name', 'known_as', 'last_name',
                                 'gender', 'profile_pic', 'profile_pic_cropping']}),
        ('Playing', {'fields': ['is_current',
                                'pref_position', 'is_umpire', 'is_coach']}),
        ('Contact', {'fields': ['email', 'phone', 'addr_street',
                                'addr_line2', 'addr_town', 'addr_postcode', 'addr_position']}),
        ('Medical', {'fields': ['dob', 'emergency_contact',
                                'emergency_relationship', 'emergency_phone', 'medical_notes']}),
    ]

    class Media:
        css = {
            'all': ('css/admin.css',)
        }

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            User = get_user_model()

            class UserChoiceField(forms.ModelChoiceField):
                def label_from_instance(self, obj):
                    full_name = f"{obj.first_name} {obj.last_name}".strip()
                    email = (obj.email or "").strip()

                    if full_name and email:
                        return f"{full_name} ({email})"
                    if full_name:
                        return full_name
                    if email:
                        return email
                    return str(obj)

            kwargs["queryset"] = User.objects.all().order_by("first_name", "last_name", "email")
            kwargs["form_class"] = UserChoiceField

        formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)

        if db_field.name == "user":
            existing = formfield.widget.attrs.get("class", "")
            formfield.widget.attrs["class"] = f"{existing} member-user-select".strip()

        return formfield

    def full_name_with_option(self, obj):
        return "{}{} {}".format(obj.first_name, " ({})".format(obj.known_as) if obj.known_as else '', obj.last_name)

    full_name_with_option.short_description = 'Name'

    def current_shirt_display(self, obj):
        assignment = obj.current_shirt_number()
        return assignment.shirt.number if assignment else '-'

    current_shirt_display.short_description = 'Shirt'


@admin.register(ShirtNumber)
class ShirtNumberAdmin(admin.ModelAdmin):
    """ Admin interface for a shirt in the pool. """
    list_display = ('number', 'gender', 'status', 'current_holder',
                    'unavailable_reason', 'unavailable_until')
    list_filter = ('status', 'gender')
    search_fields = ('number', 'assignments__member__first_name',
                     'assignments__member__known_as', 'assignments__member__last_name')
    readonly_fields = ('number', 'gender', 'status')
    ordering = ('gender', 'number')
    inlines = (ShirtAssignmentInline,)

    class Media:
        css = {'all': ('css/admin.css',)}
    fieldsets = [
        (None, {'fields': ['number', 'gender', 'status']}),
        ('Unavailability', {'fields': ['unavailable_reason', 'unavailable_until']}),
    ]
    actions = ('reconcile_status',)

    def has_add_permission(self, request):
        # Pool rows are managed via ClubInfo max + the sync_shirt_pool command.
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def current_holder(self, obj):
        assignment = obj.current_assignment()
        if assignment is None:
            return '-'
        suffix = ''
        if assignment.end_date is not None:
            suffix = ' (grace until {})'.format(assignment.end_date)
        return '{}{}'.format(assignment.member.full_name(), suffix)

    current_holder.short_description = 'Current holder'

    def reconcile_status(self, request, queryset):
        corrections = 0
        for shirt in queryset:
            old, new = shirt.recompute_status(save=True)
            if old != new:
                corrections += 1
        self.message_user(
            request,
            "Reconciled {} shirts; {} status corrections applied.".format(queryset.count(), corrections),
            level=messages.INFO)

    reconcile_status.short_description = 'Reconcile status for selected shirts'


@admin.register(SquadMembership)
class SquadMembershipAdmin(admin.ModelAdmin):
    """ Admin interface definition for the SquadMembership model."""
    model = SquadMembership
    search_fields = ('member__first_name',
                     'member__known_as', 'member__last_name')
    list_filter = ('member', 'team', 'season')
    list_display = ('__str__', 'member', 'team', 'season')


@admin.register(CommitteePosition)
class CommitteePositionAdmin(admin.ModelAdmin):
    """ Admin interface definition for the CommitteePosition model."""
    model = CommitteePosition
    search_fields = ('name',)
    list_filter = ('name', 'gender')
    list_display = ('__str__', 'name', 'gender')


@admin.register(CommitteeMembership)
class CommitteeMembershipAdmin(admin.ModelAdmin):
    """ Admin interface definition for the CommitteeMembership model."""
    model = CommitteeMembership
    search_fields = ('member__first_name',
                     'member__known_as', 'member__last_name')
    list_filter = ('member', 'position', 'season')
    list_display = ('__str__', 'member', 'position', 'season')
