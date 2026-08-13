The folder utils has files that contain functions used by most of the other files in this directory and serve various purposes.

Compactors just gets passed data and then returns it organized for usage in tables, only used for groups for the most part.
Datatable_helpers is used by the calendar and people extractors to help prep before data was upsert into the Dataverse/SQL. Can be revamped to work with the other functions and be cleaner
Env_fetcher is used to get environmental variables and then pass those to all the other files.
Hasher has one function which creates a hash that is used as a primary key for some tables that need it. An example of this is group tag, which only has two columns, group id and tag id, both of which will be used multiple times. Because of it being used multiple times, it cannot be a PK. So the hasher creates a hash based off of the two. I used Hash IDs whenever there wasn't a viable ID that could be used as a primary key. Instructions for use will be in the dedicated file.
Metering contains functions that can calculate GB/s which is one of the main billing metrics in an Azure Function. I used it when I was first testing to get an estimate of cost, but then haven't really used it since.
Response_parsers contains some functions that help parse API responses for use in tables. Used by Calendar and People.
Time_functions has functions related to time that are used by other files to parse out and convert datetimes when needed.