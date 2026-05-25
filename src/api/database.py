import os
from sqlmodel import SQLModel, create_engine, Session

# 1. Get the absolute path of the directory containing THIS file (src/api/)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sqlite_file_path = os.path.join(BASE_DIR, "compliance_vault.db")

# 2. Define the Database URL for SQLite
sqlite_url = f"sqlite:///{sqlite_file_path}"

# 3. Configure the Engine
connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, echo=True, connect_args=connect_args)

def create_db_and_tables():
    """Generates the physical tables in SQLite inside src/api/."""
    import src.api.models 
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
