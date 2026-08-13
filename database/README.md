This folder is where a lot of the action happens. This is how the functions connect to the database, upsert data, queries built, tables configured, and such.

Converters.py is used to convert (wow surprising) various datetimes into SQL compatible datetimes. This is mainly used by the check-ins.
Database.py is used to actually connect to the database. When testing locally, it uses your Azure credentials, when running in Azure Function, it uses its credentials. Server and database to connect to are configured in environmental variables.
Dropper.py is used to drop tables quickly if need be, can be faster then using SQL queries if one is need to drop a lot of tables.
Fetch_record.py is used to get data from the database, mainly the date and times of the last delta records, so that a true delta happens.
Loader.py is what actually upserts data into the database. It loads data into staging tables, then has SQL upsert into the actual tables, then truncate the staging tables, and if need be, update the delta record.
Prepper.py is pretty simple, just pings the database to make sure it is awake. It's used by pretty much all of the orchestrators at the start of their run to ensure the database is online and active for when the data is fetched.
Queries.txt contains all of the queries used so far in making the tables in the database, so if they need to be recreated they can be.
SQL_builders.py builds the actual SQL queries, based off of table_configs.py. It gets the current table and the columns needed and table names, then builds a query that can be run by loader.py
Table_configs.py is the configuration file for all of the tables that are going to be in the database. This is where columns are specified and primary columns needed. When adding new tables to the database, make sure to go to this file and use the format from other tables so that sql_builders can work properly. More instructions will be in that file.