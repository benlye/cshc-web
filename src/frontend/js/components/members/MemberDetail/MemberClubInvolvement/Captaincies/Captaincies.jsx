import React from 'react';
import PropTypes from 'prop-types';
import groupBy from 'lodash/groupBy';
import keys from 'lodash/keys';
import sortBy from 'lodash/sortBy';
import { Timeline2, Timeline2Item, CustomScrollbar } from 'components/Unify';
import Urls from 'util/urls';

/**
 *  A list of team captaincies, grouped by season.
 */
const Captaincies = ({ data }) => {
  // Group captaincies by season
  const grouped = groupBy(data.results, c => c.season.slug);
  // Sort by (descending) season (most recent season first)
  const sorted = sortBy(keys(grouped), seasonSlug => -parseInt(seasonSlug.split('-')[0], 10));
  if (!data.results || !data.results.length) {
    return <p className="g-font-style-italic text-center">(No captaincies)</p>;
  }
  return (
    <CustomScrollbar maxHeight="200px">
      <Timeline2 className="g-pb-40">
        {sorted.map(seasonSlug => (
          <Timeline2Item key={seasonSlug} dateSmall={seasonSlug}>
            {grouped[seasonSlug].map(c => (
              <h6 className="h6" key={`${c.team.slug}-${c.isVice}`}>
                <a href={Urls.clubteam_detail(c.team.slug)} title={`View ${c.team.longName} details`}>
                  {c.team.longName}
                </a>{' '}
                {c.isVice ? 'Vice-Captain' : 'Captain'}
              </h6>
            ))}
          </Timeline2Item>
        ))}
      </Timeline2>
    </CustomScrollbar>
  );
};

Captaincies.propTypes = {
  data: PropTypes.shape().isRequired,
};

export default Captaincies;
