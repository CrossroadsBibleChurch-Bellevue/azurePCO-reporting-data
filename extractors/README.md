This is the extractors folder, which contains its namesake, the extractors that are used by the orchestrators for data fetching.

The main folder itself, extractors, contains all of the extractors, which are more or less mirrors, meaning groups delta is similar to groups full. The file api_fetcher is used by both Calendar and People, when I was trying to consolidate much of the API call functions into one file. I kinda gave up on that, since Groups and CheckIns have theirs elsewhere.

The extractors themselves are not too complex, they just kinda go through and call some other function in other files to get the data, then passes that data into other functions, some of which are in other files. It's kinda an orchestrator of some sorts but not as much.

There are some other subfolders with this that are used, fetchers, builders, schemas, and cache_stashers.
Fetchers is used by Calendar, CheckIns, and Groups, to try to consolidate some functions that were being used by both the full and delta refreshes. They pretty much just do what it seems like, which is actually fetch the data.
Builders takes the data that was fetched and then actually builds the data into tables that can be used to upsert into SQL.
Schemas is used by Calendar and People. I initially used this method with calendar and then people was the next endpoint I did so then I did a similar thing. I ended up not really needing them but they already worked so I didn't change them. Basically what they do is take the data and then properly formulate the tables that will be used in SQL. It does make it easy to add or remove data that you may need.
Cache_Stashers is used by Calendar to enrich previously fetched data. So if we have an event then cache stasher would enrich it by providing details of the event.