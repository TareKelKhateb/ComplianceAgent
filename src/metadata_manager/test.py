from src.metadata_manager import MetadataStore

manager = MetadataStore() 

local_path = r"D:\ITI\dummy.pdf" 

success = manager.sync_to_dagshub(local_path)

if success:
    print("Done")
else:
    print("issue")

