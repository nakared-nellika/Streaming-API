import json
import os

# Get the directory where this script is located
current_dir = os.path.dirname(os.path.abspath(__file__))
# Navigate to the prompts directory relative to this script's location
prompts_dir = os.path.join(current_dir, "..", "prompts")

all_prompts = {}
prompts_to_load = [
    "intent_system",
    "case_summary_system",
    "case_summary_user",
    "general_system",
    "transaction_analyze_system",
    "transaction_analyze_user"]

for prompt in prompts_to_load:
    prompt_name = prompt.split("_")[:-1]
    if len(prompt_name) == 1:
        prompt_name = prompt_name[0]
    else:
        prompt_name = "_".join(prompt_name)
    prompt_sub = prompt.split("_")[-1]
    if prompt_sub == "system":
        
        with open(os.path.join(prompts_dir, prompt_name, "system_prompt.txt"), "r", encoding="utf-8") as f:
            all_prompts[prompt] = f.read()
    elif prompt_sub == "user":
        with open(os.path.join(prompts_dir, prompt_name, "user_prompt.txt"), "r", encoding="utf-8") as f:
            all_prompts[prompt] = f.read()

