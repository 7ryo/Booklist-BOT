import os
from dotenv import load_dotenv
import google.generativeai as genai

# 1. 載入環境變數
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=api_key)

print("🔍 正在查詢可用模型清單...")

try:
    # 2. 呼叫 Google 官方 SDK 的 list_models
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"✅ 模型名稱: {m.name}  (顯示名稱: {m.display_name})")
            
except Exception as e:
    print(f"❌ 無法獲取清單，錯誤原因: {e}")