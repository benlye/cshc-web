"""
  Views for Awards and Award Winners
"""

from django.views.generic import TemplateView
from members.models import Member
from .models import EndOfSeasonAwardWinner, EndOfSeasonAward


class EndOfSeasonAwardWinnersView(TemplateView):
    """ View with a list of all members"""
    template_name = 'awards/eos_list.html'

    def get_context_data(self, **kwargs):
        context = super(EndOfSeasonAwardWinnersView,
                        self).get_context_data(**kwargs)

        season_list = list(EndOfSeasonAwardWinner.objects.values_list(
            'season__slug', flat=True).distinct())
        award_list = list(EndOfSeasonAward.objects.order_by('name').values(
            'name', 'id').distinct())
        # Build the awardee filter list from Member instances so that anonymous members
        # are shown as "Anonymous Player" rather than by their real name.
        awardee_list = [
            {'id': m.id, 'first_name': m.public_pref_first_name(), 'last_name': m.public_last_name()}
            for m in Member.objects.filter(
                awards_endofseasonawardwinner_awards__isnull=False).distinct()
        ]
        context['props'] = {
            'seasons': season_list,
            'awards': award_list,
            'awardees': awardee_list,
        }
        return context
