from src.Parsing_and_metadata_extractor.parsing_and_metadata_extractor import ParsingMetaDataExtractor


if __name__ == "__main__":
    
    parser = ParsingMetaDataExtractor()
    
    
    scrapped_data = parser.fetch_incoming_data( url="https://www.cbe.org.eg/en/laws-regulations/laws/banking-laws",
                                                is_crawl=False,
                                                limit=1)


