import os
from database import Base, engine

# This drops all tables defined in Base and recreates them
print("Dropping all existing tables...")
Base.metadata.drop_all(bind=engine)

print("Recreating all tables with new schema...")
Base.metadata.create_all(bind=engine)

print("Done!")
