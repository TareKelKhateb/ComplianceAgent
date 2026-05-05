

import json
from src.Parsing_and_metadata_extractor.parsing_and_metadata_extractor import ParsingMetaDataExtractor


if __name__ == "__main__":
    
    parser = ParsingMetaDataExtractor()
    
    
    print("Fetching data from microservice...")
    
    scrapped_data = parser.fetch_incoming_data( url="https://www.cbe.org.eg/en/laws-regulations/laws/banking-laws")

    # Check if the extraction was successful before trying to save
    if scrapped_data:
        
        output_filename = "output_1.json"
        
        with open(output_filename, "w", encoding="utf-8") as f:
            # indent=4 makes the JSON easily readable in VS Code
            json.dump(scrapped_data, f, ensure_ascii=False, indent=4)
            
        print(f"✅ Success! Data cached locally to: {output_filename}")
        
    else:
        print("⚠️ Extraction failed or returned empty. No file was saved.")
