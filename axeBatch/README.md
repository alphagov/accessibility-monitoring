# Axe Batch Processor

A process that orchestrates the testing of web pages with [Deque Axe](https://github.com/dequelabs/axe-core), via the [Axe-Runner](https://github.com/alphagov/accessibility-monitoring/tree/axebatch/axe_runner) service in this repository.

It has been designed to run in [GOV.UK's Platform-as-a-Service (PaaS)](https://www.cloud.service.gov.uk/), which is based upon [CloudFoundry](https://www.cloudfoundry.org/).

This is a _prototype_ service. **It is NOT production-ready.**

## Dependencies

* [Axe-Runner](https://github.com/alphagov/accessibility-monitoring/tree/axebatch/axe_runner)
* The GOV.UK Accessibility Team's Postgres database of UK Public Sector Domains
* A Postgres database in which to store the results of tests

## Operation

The process _currently_:
* Selects a domain at random from the database of public sector websites
* Checks to see if it has been tested within the last year<sup id="a1">[1](#f1)</sup>, and if not
* Passes the domain to [Axe-Runner](https://github.com/alphagov/accessibility-monitoring/tree/axebatch/axe_runner)
* If a failure is returned, prepends "www." to the domain name and passes it back to Axe-Runner
* Records the results returned from Axe-Runner (whether successful or not) in a postgres database.

<b id="f1">1</b>  Why not just exclude already-tested domains from the list? Because the source (public sector domains) and target (test results) are in different database schema.   
Whilst (some) RDBMSs allow queries across schema, not all do - and these schema may in future even be in different databases.  
Besides, it's _neater_. [↩](#a1)

## Future developments
This is a short-term implementation to test all the domains that we have on record.
The long-term use of this tool will be to process a list of specific domains.
