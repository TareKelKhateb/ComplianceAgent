# pyrefly: ignore [missing-import]
from src.inference import ComplianceEngine

def test_system():
    engine = ComplianceEngine()
    
    query = "وفقاً للضوابط الواردة في تعليمات البنك المركزي المصري بشأن (مكافحة غسل الأموال وتمويل الإرهاب)، ما هي الإجراءات الواجب اتباعها عند التعامل مع عميل من 'عالي المخاطر' (High-Risk Customer)، وكيف تختلف هذه الإجراءات عن متطلبات العميل العادي؟"
    
    print(f"--- Question: {query} ---\n")
    
    try:
        response = engine.run(query)
        print("--- Answer ---")
        print(response)
    except Exception as e:
        print(f"An error occurred during execution: {e}")

if __name__ == "__main__":
    test_system()