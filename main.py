import os
from PIL import Image
from rich import print
from google import genai
API_KEY = "..."

client = genai.Client(api_key=API_KEY)

PROMPT = """
You are an expert accountant. Please extract the invoice information from the image and return it in the exact JSON format below.
IMPORTANT RULE: For all monetary values (total_amount, unit_price, total_price), you MUST append " VND" after the numbers. For example: "59000 VND".

{
    "store_name": "",
    "purchase_date": "",
    "total_amount": "59000 VND",
    "items": [
        {"item_name": "", "quantity": 1, "unit_price": "29000 VND", "total_price": "29000 VND"}
    ]
}

YOU MUST RETURN ONLY VALID JSON. DO NOT ADD ANY MARKDOWN, EXPLANATIONS, OR EXTRA TEXT.
"""

def process_invoice(image_path, output_filename):
    print(f"[bold yellow]Processing invoice: {image_path}...[/bold yellow]")
    try:
        img = Image.open(image_path)
        
        response = client.models.generate_content(
            model='gemini-2.5-flash', 
            contents=[PROMPT, img]
        )
        
        json_string = response.text.replace("```json", "").replace("```", "").strip()
        
        print("[bold green]✅ Successfully extracted![/bold green]")
        print(json_string)
        
        with open(output_filename, "a", encoding="utf-8") as file:
            file.write(f"--- Invoice: {image_path} ---\n")
            file.write(json_string + "\n\n")
            
    except Exception as e:
        print(f"[bold red]❌ Error processing {image_path}: {e}[/bold red]")
        with open(output_filename, "a", encoding="utf-8") as file:
            file.write(f"--- Error: {image_path} ---\n")
            file.write(str(e) + "\n\n")

if __name__ == "__main__":
    folder_name = "invoices"
    output_file = "extracted_data.txt"
    
    with open(output_file, "w", encoding="utf-8") as file:
        file.write("=== INVOICE EXTRACTION RESULTS ===\n\n")
        
    print(f"[bold cyan]Results will be saved to: {output_file}[/bold cyan]\n")
    image_list = [os.path.join(folder_name, f) for f in os.listdir(folder_name) if f.lower().endswith(('.jpg', '.png', '.jpeg'))]
    
    if len(image_list) == 0:
        print(f"[bold red]⚠️ No images found in the '{folder_name}' folder.[/bold red]")
    else:
        for img_path in image_list:
            process_invoice(img_path, output_file)
            print("-" * 50)
            
        print(f"[bold green]🎉 All done! Check the '{output_file}' file for your data.[/bold green]")