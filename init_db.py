from database import Base, engine

def create_tables():
    if not engine:
        print("❌ DATABASE_URL is not set.")
        return
    print("⏳ Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("✅ Tables created successfully!")

if __name__ == "__main__":
    create_tables()