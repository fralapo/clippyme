import os
import shutil
from hooks import create_hook_image

def verify():
    print("🧪 Verifying Hook Image Generation...")
    
    test_text = "POV: You are testing the viral hook feature\nand it works perfectly."
    output_path = "test_hook.png"
    target_width = 800
    
    try:
        path, w, h = create_hook_image(test_text, target_width, output_image_path=output_path)
        
        print(f"✅ Image generated at {path}")
        print(f"   Dimensions: {w}x{h}")
        
        if not os.path.exists(path):
            print("❌ File does not exist")
            return False
            
        if os.path.getsize(path) == 0:
            print("❌ File is empty")
            return False
            
        print("✨ Verification Successful!")
        return True
    except Exception as e:
        print(f"❌ Verification Failed: {e}")
        return False
    finally:
        if os.path.exists(output_path):
             os.remove(output_path)

if __name__ == "__main__":
    verify()
