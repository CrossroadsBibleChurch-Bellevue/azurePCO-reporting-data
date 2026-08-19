This repo contains the necessary code to successfully pull data from Planning Center People, Groups, Check-Ins, and Registrations and then upload data into Azure SQL DB. Gets the main relevant data needed for analytics and reporting, so not all data is fetched and uploaded. Contains necessary files to connect to DB, PCO, queries needed, etc. This system is designed to do delta refresh for people, groups, and check-ins once per day, registrations once per week, and full refreshes of people, groups, and check-ins once a month. This is designed to run on an Azure Function so as to reduce manual input and run autonomously.

To run this, clone the repo and then make sure to create the .env file from the example included. After that it can be run locally using Azurite and a local Azure Function or the individual functions can be run through calling their orchestrator. Deploying this to Azure Function is not that difficult either. Just make sure to put the environmental variables in the variables in the Function and then deploy it, then test to make sure. Also change the timers to desired schedules. Make sure to create the user for the Azure Function in the database and give proper permissions.

When adding a new endpoint from PCO for usage, follow the structures used by the other endpoints, adding to table configs, create an orchestrator and extractor, and adding the necessary entry in the SQL as well as update in loader if doing a delta refresh.

In this repo, there are more detailed README files in each folder going into what each file does, and then each file has some documentation that should in theory explain usage.

## Roadmap
- Finish up services endpoint
    - Make sure all correct table and PK columns are fetched, check against the ERD
    - Remove unnecessary data from tables
    - Create delta version
    - Verify delta version works
    - Put into project directory
    - Hook up to everything (follow new endpoint process below)
    - Test locally
    - Deploy to Azure
- Start Giving endpoint
- Follow process below for giving
- Finish giving endpoint

## Process for creating new endpoint
- Make a tester version
- Verify correct tables as in the ERD
- Verify correct PK columns as in ERD
- Take out unnecessary data from tables
- Create a delta version off of the full data version
- Verify delta works as needed
- Put into project directory
- Create orchestrator that calls the extractor (the files that were just put into project directory, just copy and past another extractor and adapt as needed)
- Verify that orchestrator gets correct format (use sql tester since it has code at the bottom that steps through the extractor output)
- Create table configs that match columns and tables needed
- Create queries for tables
- Run orchestrator fully as a test to ensure that data is upserted successfully
- Run function locally (using func start and azurite)
- Deploy to Azure Function to ensure it works on Azure

## Main Important Files
- function_app.py
    - The main driver and how the whole azure function works, without this file, it doesn't run.
    - Each orchestrator more or less has its own timer, just make sure the schedules won't conflict between functions, giving enough time for the previous function to finish before starting the next one
- table_configs.py
    - One of the more important files, this one contains each table of the SQL and then maps the columns in SQL to dictionary keys
    - In this file there is documentation on how to create a new table config when adding new tables.
- loader.py
    - This file takes the data fetched from the extractors and orchestrators and then puts it into queries to be uploaded into SQL. Don't need to understand it a ton and shouldn't need to mess with it too much, but may need to debug in it when adding new endpoints.
- queries.txt
    - File contains all the queries I used for tables and indexes, if tables needed to be removed for whatever reason
- Any orchestrator
    - All the orchestrators are more or less the same, just fetches data from the extractor and then gives it to the loader, some have a bit more steps involved when its dealing with a lot of data but not too much
- Extractors
    - These are each kinda unique, basically for each endpoint I have a delta and a full refresh version, but I try to reuse as many function in each as possible and then put those functions in a shared file so that the extractors are not as long.
    - The extractors are the main drivers, they fetch the data, parse through it, then build the data into tables


## Overall flow of the whole process
1. Function app schedule hits its mark, runs function (the orchestrator)
2. Orchestrator wakes server up, then calls extractor to fetch data
3. Extractor fetches data from Planning Center Online (PCO) API and receives response JSON
4. Extractor takes JSON, parses through it to get relevant data
5. Extractor then takes parsed data and builds into dictionaries/tables
6. Extractor passes dictionaries back to orchestrator
7. Orchestrator takes dictionaries and pass them to loader
8. Loader steps through dictionary using table configs as a map to get data from dictionary and correlate to proper columns in SQL
9. Loader then takes correlate values and columns and uploads into staging table in SQL
10. Loader then tells SQL to upsert from staging table into actual table
11. Loader repeats steps 8-10 for all tables
12. Loader truncates staging tables and updates delta record if needed
13. Function finishes


## Known Errors
Some errors that I encountered a lot occurs when trying to use fast_executemany (which we use since it speeds uploading time up) and using it with datetimes. Basically the problem is that the datetimes are not formatted correctly, so because of this SQL throws an error. The fix for this is to use convert_output_datetimes_to_local_sql from time_functions in the util folder. This goes through the data and cchanges the datetimes into the proper format for SQL. Just make sure the column that has the date and time is in the set at the top of the file, SQL_DATETIME_FIELD_NAMES.
Another error is very similar. Basically gets given ID's that Python has as Strings but SQL has as INT, because it is trying to upsert quickly, SQL fails and throws an error. Just make sure the IDs are INTs and not Strings.
An error I got once or twice was again caused by fast_executemany where the first value or two was None so it assumed thats what they all should be and thus failed when given a non-None value. This was fixed by using set input_sizes in table_configs. There is an example of this with the signup and checkins_events table. I would recommend getting AI's help in determining those for the table.
With Azure Function there is an error where the function will just stop after about 60 minutes, and you get no error message. To solve this I just split the functions up so it didn't take as long. It's a little scuffed but it works.


Summary of main important files
How to implement giving basically
