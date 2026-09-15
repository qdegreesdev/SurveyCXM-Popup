from test_category_generator import (
    test_generate_categories_success,
    test_generate_categories_custom_counts,
    test_generate_categories_invalid_secret_key,
    test_generate_categories_invalid_client_id,
    test_generate_categories_invalid_industry_name
)

def main():
    print("Running Category Generator API tests...")
    
    test_generate_categories_success()
    print("  [PASS] test_generate_categories_success")
    
    test_generate_categories_custom_counts()
    print("  [PASS] test_generate_categories_custom_counts")
    
    test_generate_categories_invalid_secret_key()
    print("  [PASS] test_generate_categories_invalid_secret_key")
    
    test_generate_categories_invalid_client_id()
    print("  [PASS] test_generate_categories_invalid_client_id")
    
    test_generate_categories_invalid_industry_name()
    print("  [PASS] test_generate_categories_invalid_industry_name")
    
    print("\nSUCCESS: All Category Generator API tests passed successfully!")

if __name__ == "__main__":
    main()
