import json
import re
from typing import Optional, List, Dict, Any, Tuple
from openai import OpenAI
from loguru import logger
from config import settings

# List of known standard industries for validation & fallback matching
KNOWN_INDUSTRIES = [
    "Healthcare & Medical",
    "Retail & Supermarkets",
    "Banking, Financial Services & Insurance (BFSI)",
    "E-Commerce & Digital Shopping",
    "Hospitality & Hotel Management",
    "Software & SaaS",
    "Education & Academics",
    "Telecommunications",
    "Automotive & Transportation",
    "Real Estate & Construction",
    "Food & Beverage / Restaurants",
    "Travel, Aviation & Tourism",
    "Energy & Utilities",
    "Manufacturing & Industrial",
    "Media, Entertainment & Gaming",
    "Logistics & Supply Chain",
    "Professional Services & Consulting",
    "Fashion & Apparel",
    "Fitness & Wellness",
    "Government & Public Sector"
]

def validate_industry_name(industry_name: Any) -> Tuple[bool, str]:
    """
    Validates and cleans the industry name.
    Returns (is_valid, cleaned_name_or_error_message).
    """
    if not industry_name or not isinstance(industry_name, str):
        return False, "Industry name must be a non-empty string."
    
    cleaned = industry_name.strip()
    if len(cleaned) < 2:
        return False, "Industry name must be at least 2 characters long."
    
    if len(cleaned) > 100:
        return False, "Industry name must not exceed 100 characters."

    # Check for invalid control characters or script injection
    if re.search(r"[<>{}\\]", cleaned):
        return False, "Industry name contains invalid or special characters."
    
    return True, cleaned

def get_fallback_categories(industry_name: str, category_creation_count: int = 5, subcategory_creation_count: int = 3) -> List[Dict[str, Any]]:
    """
    Returns main categories and sub-categories based on category_creation_count & subcategory_creation_count.
    """
    ind_lower = industry_name.lower()

    if any(k in ind_lower for k in ["health", "hospital", "clinic", "pharma", "medical"]):
        base = [
            {
                "category_name": "Patient Experience & Care Quality",
                "sub_categories": ["Doctor & Nurse Behavior", "Treatment & Care Explanation", "Medical Staff Responsiveness", "Care Follow-up", "Diagnosis Accuracy"]
            },
            {
                "category_name": "Facility & Cleanliness",
                "sub_categories": ["Hygiene & Sanitation", "Room Comfort & Amenities", "Waiting Area Environment", "Restroom Cleanliness", "Noise Control"]
            },
            {
                "category_name": "Appointment & Scheduling",
                "sub_categories": ["Booking Process", "Wait Time & Timeliness", "Registration & Check-In", "Rescheduling Ease", "Reminder System"]
            },
            {
                "category_name": "Billing & Insurance Administration",
                "sub_categories": ["Price Transparency", "Insurance Claim Processing", "Billing Accuracy", "Payment Options", "Financial Counseling"]
            },
            {
                "category_name": "Pharmacy & Lab Support",
                "sub_categories": ["Medicine Availability", "Lab Test Turnaround Time", "Report Delivery", "Prescription Clarity", "Sample Collection"]
            },
            {
                "category_name": "Emergency Services & Response",
                "sub_categories": ["Ambulance Speed", "Triage Efficiency", "Emergency Room Staffing", "Trauma Support"]
            }
        ]
    elif any(k in ind_lower for k in ["retail", "ecommerce", "e-commerce", "shop", "store"]):
        base = [
            {
                "category_name": "Product Quality & Selection",
                "sub_categories": ["Product Variety", "Stock Availability", "Item Freshness & Quality", "Brand Options", "Sizing & Fit"]
            },
            {
                "category_name": "Store & Checkout Experience",
                "sub_categories": ["Staff Assistance", "Checkout Speed & Lines", "Store Ambiance & Cleanliness", "Aisle Organization", "Self-Checkout Systems"]
            },
            {
                "category_name": "Pricing & Value for Money",
                "sub_categories": ["Competitive Pricing", "Promotions & Discounts", "Transparency of Cost", "Loyalty Rewards", "Price Matching"]
            },
            {
                "category_name": "Order Delivery & Logistics",
                "sub_categories": ["Delivery Speed", "Packaging Quality", "Real-Time Tracking", "Unboxing Experience", "Shipping Cost"]
            },
            {
                "category_name": "Returns & Customer Support",
                "sub_categories": ["Return & Refund Policy", "Support Ticket Resolution", "Refund Speed", "Exchange Process", "Help Center Clarity"]
            }
        ]
    elif any(k in ind_lower for k in ["bank", "finan", "insurance", "bfsi", "invest"]):
        base = [
            {
                "category_name": "Digital & Mobile Banking",
                "sub_categories": ["App Ease of Use", "Transaction Speed", "Online Portal Security", "Biometric Login", "Feature Richness"]
            },
            {
                "category_name": "Branch & In-Person Services",
                "sub_categories": ["Staff Courtesy & Expertise", "Queue Management", "Branch Ambiance", "ATM Availability", "Desk Service"]
            },
            {
                "category_name": "Account & Financial Products",
                "sub_categories": ["Interest Rates & Fees", "Loan & Card Approval", "Product Transparency", "Investment Guidance", "Fee Waiver Ease"]
            },
            {
                "category_name": "Customer Support & Query Resolution",
                "sub_categories": ["Call Center Wait Time", "Issue Resolution Speed", "Support Representative Knowledge", "Escalation Handling", "24/7 Availability"]
            },
            {
                "category_name": "Security & Fraud Prevention",
                "sub_categories": ["Alerts & Notifications", "Card & Password Safety", "Account Verification Process", "OTP Speed", "Fraud Resolution"]
            }
        ]
    elif any(k in ind_lower for k in ["tech", "software", "saas", "it", "app"]):
        base = [
            {
                "category_name": "Product Usability & UI/UX",
                "sub_categories": ["Interface Intuitive Design", "Feature Navigation", "Customization Options", "Mobile Responsiveness", "Dark Mode & Accessibility"]
            },
            {
                "category_name": "System Performance & Reliability",
                "sub_categories": ["Platform Uptime & Speed", "Bug & Error Frequency", "API Integration Performance", "Data Synchronization", "Load Time"]
            },
            {
                "category_name": "Customer Support & Success",
                "sub_categories": ["Technical Support Speed", "Knowledge Base & Docs", "Dedicated Account Management", "Ticket Escalation", "Live Chat Response"]
            },
            {
                "category_name": "Onboarding & Implementation",
                "sub_categories": ["Setup Simplicity", "User Training & Tutorials", "Migration Assistance", "Initial Configuration", "Welcome Guide"]
            },
            {
                "category_name": "Pricing & Licensing",
                "sub_categories": ["Plan Flexibility", "Billing Clarity", "Value Realization", "Tier Upgrades", "Seat Allocation"]
            }
        ]
    elif any(k in ind_lower for k in ["hotel", "hospitality", "resort", "restaurant", "food", "gym", "fitness"]):
        base = [
            {
                "category_name": "Facility Cleanliness & Environment",
                "sub_categories": ["Hygiene Standards", "Equipment/Room Maintenance", "Ambiance & Lighting", "Restroom Cleanliness", "Temperature Control"]
            },
            {
                "category_name": "Service & Staff Hospitality",
                "sub_categories": ["Staff Warmth & Courtesy", "Order/Task Speed", "Attentiveness & Care", "Staff Knowledge", "Problem Resolution"]
            },
            {
                "category_name": "Product & Offering Quality",
                "sub_categories": ["Taste/Equipment Variety", "Quality & Standards", "Freshness & Condition", "Customization Options", "Presentation"]
            },
            {
                "category_name": "Booking & Reception Experience",
                "sub_categories": ["Check-In/Reservation Process", "Front Desk Helpfulness", "Special Request Handling", "Wait Time", "Ease of Entry"]
            },
            {
                "category_name": "Pricing & Overall Value",
                "sub_categories": ["Rates & Fee Structure", "Value for Money", "Billing Accuracy", "Package Deals", "Membership Perk Value"]
            }
        ]
    else:
        base = [
            {
                "category_name": f"{industry_name} Product & Service Quality",
                "sub_categories": ["Feature Standards", "Consistency & Reliability", "Value & Offering Fit", "Quality Control", "Design & Finish"]
            },
            {
                "category_name": "Customer Service & Support",
                "sub_categories": ["Response Time", "Staff Knowledge & Courtesy", "Issue Resolution Speed", "Helpfulness", "Follow-up Communication"]
            },
            {
                "category_name": "Process & Delivery Efficiency",
                "sub_categories": ["Turnaround Time", "Ease of Process", "Communication & Status Updates", "Order Precision", "Schedule Adherence"]
            },
            {
                "category_name": "Pricing & Transparency",
                "sub_categories": ["Cost Competitiveness", "Invoice & Billing Accuracy", "Pricing Structure Clarity", "Discount Programs", "No Hidden Charges"]
            },
            {
                "category_name": "Overall Experience & Brand Trust",
                "sub_categories": ["Brand Reliability", "Ease of Doing Business", "Customer Recommendation Propensity", "Trustworthiness", "Contract Flexibility"]
            }
        ]

    # Adjust counts according to requested category_creation_count and subcategory_creation_count
    result = []
    for idx in range(category_creation_count):
        if idx < len(base):
            cat_item = base[idx]
            cat_name = cat_item["category_name"]
            sub_list = cat_item["sub_categories"]
        else:
            cat_name = f"{industry_name} Additional Aspect {idx + 1}"
            sub_list = [f"Sub Aspect {i+1}" for i in range(subcategory_creation_count)]

        # Adjust subcategories count
        final_subs = []
        for sub_idx in range(subcategory_creation_count):
            if sub_idx < len(sub_list):
                final_subs.append(sub_list[sub_idx])
            else:
                final_subs.append(f"{cat_name} Feature {sub_idx + 1}")

        result.append({
            "category_id": idx + 1,
            "category_name": cat_name,
            "sub_categories": final_subs
        })

    return result

def generate_industry_categories(
    industry_name: str,
    client_id: int,
    survey_id: int,
    category_creation_count: int = 5,
    subcategory_creation_count: int = 3
) -> List[Dict[str, Any]]:
    """
    Generates category_creation_count main categories and subcategory_creation_count sub-categories per category
    tailored to the given industry using OpenAI or returns structured fallbacks.
    """
    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-your"):
        logger.warning(f"No valid OpenAI API key — using fallback category generator for industry '{industry_name}'.")
        return get_fallback_categories(industry_name, category_creation_count, subcategory_creation_count)

    try:
        client = OpenAI(api_key=settings.openai_api_key)

        prompt = f"""
You are a Customer Experience (CX) expert specializing in survey design and classification frameworks.
Generate EXACTLY {category_creation_count} main categories relevant to customer feedback for the industry: "{industry_name}".
For EACH of the {category_creation_count} main categories, generate EXACTLY {subcategory_creation_count} relevant sub-categories.

Output MUST be strictly a valid JSON object matching this schema:
{{
  "categories": [
    {{
      "category_id": 1,
      "category_name": "Main Category Title",
      "sub_categories": ["Sub Category 1", "Sub Category 2", "Sub Category 3"]
    }},
    ... (exactly {category_creation_count} items, category_id 1 to {category_creation_count})
  ]
}}

Requirements:
- Main categories must be highly relevant and distinct for the "{industry_name}" industry.
- Each main category must contain EXACTLY {subcategory_creation_count} concise sub-categories.
- category_id should be integers 1 to {category_creation_count}.
- Do NOT add markdown code blocks or explanatory text outside the JSON.
"""

        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=800,
            response_format={"type": "json_object"}
        )

        content = response.choices[0].message.content.strip()
        data = json.loads(content)
        categories = data.get("categories", [])

        # Validate structure returned by AI
        if not isinstance(categories, list) or len(categories) != category_creation_count:
            logger.warning(f"AI returned category count ({len(categories) if isinstance(categories, list) else 0}) != requested count ({category_creation_count}). Adjusting...")

        sanitized_categories = []
        for idx in range(1, category_creation_count + 1):
            cat_obj = categories[idx - 1] if isinstance(categories, list) and idx <= len(categories) and isinstance(categories[idx - 1], dict) else {}
            cat_name = str(cat_obj.get("category_name", f"Category {idx}")).strip()
            
            sub_cats = cat_obj.get("sub_categories", [])
            if not isinstance(sub_cats, list):
                sub_cats = []
            
            sanitized_sub_cats = []
            for sub_idx in range(1, subcategory_creation_count + 1):
                if sub_idx <= len(sub_cats) and sub_cats[sub_idx - 1]:
                    sanitized_sub_cats.append(str(sub_cats[sub_idx - 1]).strip())
                else:
                    sanitized_sub_cats.append(f"{cat_name} Feature {sub_idx}")

            sanitized_categories.append({
                "category_id": idx,
                "category_name": cat_name,
                "sub_categories": sanitized_sub_cats
            })

        return sanitized_categories

    except Exception as e:
        err_msg = str(e).lower()
        if "quota" in err_msg or "rate_limit" in err_msg or "429" in err_msg:
            logger.error(f"⚠️ OpenAI Quota Exceeded / Rate Limited ({e}). Please top up your OpenAI billing account. Falling back to rule-based category generator for '{industry_name}'.")
        else:
            logger.error(f"Error generating industry categories with OpenAI: {e}")
        return get_fallback_categories(industry_name, category_creation_count, subcategory_creation_count)
