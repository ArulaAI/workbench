# Business-domain discovery flow

Business-domain discovery runs as part of `speed digest --refresh`.

```text
speed digest --refresh / Dashboard Refresh
                    |
                    v
            acquire build lock
                    |
                    v
       load prior model + human overrides
                    |
                    v
   +--------------------------------------+
   | Deterministic extraction             |
   |                                      |
   | source inventory -> language adapters|
   | -> symbols, routes, calls, resources |
   | -> canonical entry points            |
   | -> bounded traces + evidence spans   |
   +--------------------------------------+
                    |
                    v
       business-domain-facts.json
                    |
                    v
      choose execution strategy
       /                      \
 whole graph            hierarchical packets
       \                      /
                    v
   +--------------------------------------+
   | Semantic interpretation              |
   |                                      |
   | entry points -> business activities  |
   | activities   -> rules/ownership      |
   | activities   -> business domains     |
   | claims       -> independent review   |
   +--------------------------------------+
                    |
                    v
    validate schema, references, evidence
    and confirm sources did not change
                    |
              +-----+-----+
              |           |
            valid       failure
              |           |
              v           v
   publish atomically   record status;
   business-domains.json preserve old model
              |
              v
      repository-digest.json
```

## PetClinic example

This example comes from `~/Documents/code/tmp/spring-petclinic-reactjs`.

```text
React route
/owners/:ownerId/pets/:petId/visits/new
[client/src/configureRoutes.tsx:30]
              |
              | resolved
              v
         VisitsPage
              |
        "Add Visit" button
              |
              | resolved
              v
     VisitsPage.onSubmit()
              |
              | resolved
              v
        submitForm(...)
              |
              | unresolved dynamic HTTP target
              - - - - - - - - - - - - - - - -+
                                                |
OpenAPI contract                                |
POST /owners/{ownerId}/pets/{petId}/visits <----+
              |
              | resolved implementation link
              v
OwnerRestController.addVisitToOwner()
              |
              +--> VisitMapper.toVisit()       resolved
              +--> Visit.setPet()              resolved
              +--> ClinicService.saveVisit()   unresolved call target
              +--> HTTP 201 Created
```

The inspected PetClinic discovery artifacts reported:

- 101 entry-point representations reduced to 52 canonical anchors.
- 943 symbols, 4,370 edges, and 4,144 evidence spans extracted.
- Semantic discovery stopped with `PROVIDER_UNAVAILABLE` after seven requests
  and four retries.
- Zero of 52 anchors were interpreted, so no domain model was published and
  the repository digest contained zero domains.

The source also contains a response-status conflict: the React client treats
only HTTP `204` as success, while `OwnerRestController.addVisitToOwner()`
returns HTTP `201`. The unresolved frontend-to-endpoint link meant the current
discovery artifact did not promote that conflict into a validated domain
finding.
