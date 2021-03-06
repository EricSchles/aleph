aleph.directive('searchEntitySuggest', ['$location', '$q', '$route', '$http', '$rootScope', 'Authz', 'Entity',
    function($location, $q, $route, $http, $rootScope, Authz, Entity) {
  return {
    restrict: 'E',
    scope: {
      query: '='
    },
    templateUrl: 'templates/documents/search_entity_suggest.html',
    link: function (scope, element, attrs) {
      scope.triggerLogin = $rootScope.triggerLogin;
      
      scope.createQueryEntity = function(schema) {
        var name = scope.queryText;
        name = name.replace(/[\"\'\(\)\[\]\+]*/, ' ');
        name = titleCaps(name);
        Entity.create({$schema: schema, name: name}).then(function() {
          $route.reload();
        });
      };

      scope.setEntity = function(entity) {
        scope.query.set('q', '');
        scope.query.toggle('entity', entity.id);
      };

      var shouldSuggest = function(text) {
        if (!text) return false;
        text = text.trim();
        if (text && text.length > 3 && text.indexOf(' ') != -1) {
          return true;
        }
        return false;
      };

      scope.$watch('query', function updateSearchEntitySuggest(q) {
        scope.entity = null;
        scope.offerCreate = false;
        scope.offerSignin = false;
        scope.offerEntity = false;
        scope.queryText = q ? q.getQ() : '';

        if (shouldSuggest(scope.queryText)) {
          var params = {
              params: {'prefix': scope.queryText},
              ignoreLoadingBar: true,
              cache: true
          };
          $http.get('/api/1/entities/_suggest', params).then(function(res) {
            if (res.data.results && res.data.results.length && res.data.results[0].match) {
              scope.entity = res.data.results[0];
              scope.offerEntity = true;
            } else {
              scope.offerSignin = !Authz.logged_in();
              scope.offerCreate = Authz.logged_in();
            }
          });
        }
      });

    }
  };
}]);
