from transformers import AutoTokenizer

MODEL_NAME = "visheratin/t5-efficient-mini-grammar-correction"
OUTPUT_DIR = "visheratin-t5-efficient-mini-grammar-tokenizer"

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
tokenizer.save_pretrained(OUTPUT_DIR)

print(f"Tokenizer saved to: {OUTPUT_DIR}")
