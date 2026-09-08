import gql from 'graphql-tag';
import { compose, graphql } from 'react-apollo';
import withApolloResults from 'components/common/ApolloResults';

export const CAPTAINCIES_QUERY = gql`
  query Captaincies($memberId: ID!) {
    captaincies(memberId: $memberId) {
      results(pageSize: 1000) {
        isVice
        season {
          slug
        }
        team {
          slug
          longName
        }
      }
    }
  }
`;

export const captainciesOptions = {
  options: ({ memberId }) => ({
    variables: {
      memberId,
    },
    fetchPolicy: 'cache-and-network',
  }),
  props: ({ ownProps, data: { networkStatus, error, captaincies }, ...props }) => ({
    networkStatus,
    error,
    data: captaincies,
    loadingMessage: 'Loading captaincies...',
    ...props,
  }),
};

export default compose(
  graphql(CAPTAINCIES_QUERY, captainciesOptions),
  withApolloResults,
);
