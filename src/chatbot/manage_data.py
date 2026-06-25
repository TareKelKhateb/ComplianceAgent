import os
from langchain_core.documents import Document
from chatbot.vector_db.db_maintenance import add_or_update_documents

if __name__ == "__main__":
    print("Populating Compliance Databases...")

    # INTERNAL POLICY: The company's current rule
    internal_policies = [
        Document(
            page_content="Corporate Data Retention Policy v2.1: All financial transaction records and customer communications must be securely retained for a period of exactly three (3) years. After three years, data must be permanently purged to save server costs.",
            metadata={"source": "corp_policy_dr_02", "title": "Data Retention"}
        )
    ]
    
    # EXTERNAL REGULATION: The state/federal law
    external_regulations = [
        Document(
            page_content="Financial Data Protection Act (FDPA) Section 404: Any institution handling financial transactions must maintain complete ledgers and customer correspondence for a minimum of five (5) years to ensure auditability by state regulators.",
            metadata={"source": "state_law_fdpa_404", "title": "FDPA Section 404"}
        )
    ]

    # Ingest data
    add_or_update_documents("internal_policies", internal_policies)
    add_or_update_documents("external_regulations", external_regulations)
    
    print("\nCompliance data loaded successfully!")