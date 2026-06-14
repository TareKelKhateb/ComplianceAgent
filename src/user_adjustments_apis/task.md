so right now the orchestration works like this 
1 - scrape 
2 - user adjustments (not implemented yet)
3 - ocr_pipeline 

u can see the flow in the orchestrator 

what we want to do is that a user will review the scrapping result that we have a mock result in output_scraped_1.json and adjust it 

after the adjustment we should be getting something similiar to output_1.json

the user doesn't review the pdfs themselves he just reviews the metadata title,etc ...


user adjustments should be like this 

1 - i scrape okay 
2 - an email sent to the user with a link to the user adjustments page 
3 - user adjusts the metadata 
4 - clicks approve and then a trigger to the orhcestrator to continue 

Note: 
the most important feature here is caching 
if a user maps a document with specific metadata earlier those mappings should be stored and if the same document is scraped again we should return the same metadata 


make 2 folders 
1 - api 
2 - ui 

use fastapi for the api
