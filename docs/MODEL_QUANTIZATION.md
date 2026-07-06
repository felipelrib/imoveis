# Model Quantization & Optimization Guide

## Overview

This guide covers techniques for quantizing and optimizing Vision-Language Models (VLMs) to fit within consumer GPU VRAM constraints while maintaining reasonable inference speed and accuracy.

## 1. Why Quantization?

### Challenges with Full-Precision Models
- **Memory**: Llama-3-Vision (70B) → 140 GB FP32, 70 GB FP16
- **Latency**: Slower inference on consumer hardware
- **Throughput**: Limited batch size on consumer GPUs (20-24 GB VRAM typical)

### Benefits of Quantization
- **50-75% model size reduction** (70 GB FP16 → 18-35 GB INT8/INT4)
- **2-4x faster inference** (especially on specialized hardware)
- **Lower memory bandwidth requirements**
- **Better batch throughput** on limited VRAM
- **Minimal accuracy loss** (< 2% for INT8, < 5% for INT4)

## 2. Quantization Techniques

### 2.1 Post-Training Quantization (PTQ)

Simple, fast, no retraining needed.

#### INT8 Quantization with ONNX Runtime
```bash
# Install tools
pip install onnx onnxruntime onnxruntime-tools

# Convert Hugging Face model to ONNX
python -m transformers.onnx \
  --model=meta-llama/Llama-2-7b-hf \
  --feature=causal-lm \
  onnx/llama-2-7b/

# Quantize to INT8
python -m onnxruntime.quantization.quantize_static \
  --model_input onnx/llama-2-7b/model.onnx \
  --model_output onnx/llama-2-7b-int8/model.onnx \
  --calibration_data_dir ./calibration_data \
  --quant_format QOperatorType \
  --per_channel \
  --reduce_range
```

#### Using Ollama's Built-In Quantization
```bash
# Pull pre-quantized model
ollama pull llama-3-2-vision:13b-instruct-q4_K_M

# Check available quantizations
ollama list | grep llama-3-2-vision

# Create custom quantization
ollama create my-llava \
  -f Modelfile  # See below

# Test quantized model
ollama run my-llava "What's in this image?" < /path/to/image.jpg
```

#### Custom Modelfile
```
FROM llama-3-2-vision:13b-instruct

# Reduce context window to save memory
PARAMETER num_ctx 2048

# Set temperature for consistency
PARAMETER temperature 0.7

# System prompt for better real estate analysis
SYSTEM """You are a real estate property analyzer. Provide concise assessments of property photos."""
```

### 2.2 Quantization-Aware Training (QAT)

Better accuracy but requires training data and compute.

```python
import torch
from transformers import AutoModelForCausalLM, BitsAndBytesConfig

# Quantize with bitsandbytes (8-bit)
quantization_config = BitsAndBytesConfig(
    load_in_8bit=True,
    llm_int8_threshold=200.0,
    llm_int8_has_fp16_weight=False,
)

model = AutoModelForCausalLM.from_pretrained(
    "meta-llama/Llama-2-7b",
    quantization_config=quantization_config,
    device_map="auto"
)

# Fine-tune on real estate data
from peft import LoraConfig, get_peft_model

peft_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM"
)

model = get_peft_model(model, peft_config)

# Training loop
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
)
trainer.train()
```

### 2.3 Weight-Only Quantization (GPTQ, AWQ)

Excellent balance of speed and accuracy.

#### Using GPTQ
```bash
# Install
pip install auto-gptq

# Quantize model
python
```python
from auto_gptq import AutoGPTQForCausalLM, BaseQuantizeConfig

quantize_config = BaseQuantizeConfig(
    bits=4,
    group_size=128,
    desc_act=False,
)

model = AutoGPTQForCausalLM.from_pretrained(
    "meta-llama/Llama-2-7b-hf",
    quantize_config=quantize_config,
    device_map="auto"
)

# Save quantized model
model.save_quantized("llama-2-7b-gptq")
```

#### Using AWQ
```bash
pip install autoawq

python
```python
from awq import AutoAWQForCausalLM
from transformers import AutoTokenizer

model_path = 'meta-llama/Llama-2-7b-hf'
quant_path = 'llama-2-7b-awq'
quant_config = {
    "zero_point": True,
    "q_group_size": 128,
    "w_bit": 4,
    "version": "GEMM"
}

# Load and quantize
model = AutoAWQForCausalLM.from_pretrained(model_path)
model.quantize(
    AutoTokenizer.from_pretrained(model_path),
    quant_config=quant_config
)

# Save
model.save_quantized(quant_path)
```

## 3. Model Selection for Vision Tasks

### 3.1 Comparison Matrix

| Model | Size | Parameters | Quantized | VRAM (FP16) | Speed | Accuracy |
|-------|------|------------|-----------|------------|-------|----------|
| Llama-3-2-Vision | 13B | 13B | 3.5-7GB | 28 GB | ⭐⭐ | ⭐⭐⭐⭐ |
| LLaVA-1.6 | 7B | 7B | 2-4GB | 15 GB | ⭐⭐⭐ | ⭐⭐⭐ |
| Moondream | 2.5B | 2.5B | 1-2GB | 6 GB | ⭐⭐⭐⭐ | ⭐⭐ |
| Qwen-2-VL-Small | 2B | 2B | 0.8-1.5GB | 4 GB | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| Phi-3.5-Vision | 4.2B | 4.2B | 1-2GB | 8 GB | ⭐⭐⭐⭐ | ⭐⭐⭐ |

### 3.2 Model Downloads

```bash
# Using Ollama
ollama pull moondream
ollama pull qwen:0.5b-chat-q4_K_M
ollama pull phi:3.5-vision-q4_K_M

# Using Hugging Face
huggingface-cli download \
  Qwen/Qwen-VL-Chat \
  --local-dir ./models/qwen-vl-chat

# Using LM Studio
# GUI-based download from https://lmstudio.ai
```

## 4. Optimization Techniques

### 4.1 Memory Optimization

#### Gradient Checkpointing
```python
model.gradient_checkpointing_enable()  # Save memory during training
```

#### Flash Attention
```python
# Faster, more memory-efficient attention mechanism
from flash_attn import flash_attn_func
# Automatically used in newer models if available
```

#### Offloading Strategies
```python
import torch

# CPU offloading (slower but enables larger models)
model = model.half().to('cpu')

# GPU offloading for inference
from transformers import GPTQConfig
config = GPTQConfig(bits=4, dataset="wikitext")
model = AutoModelForCausalLM.from_pretrained(..., quantization_config=config)

# NVMe offloading (very slow, emergency only)
# Not typically useful for real-time inference
```

### 4.2 Inference Optimization

#### Batching
```python
# Process multiple images at once
images = [Image.open(path) for path in image_paths]
batch_size = 4

for i in range(0, len(images), batch_size):
    batch = images[i:i+batch_size]
    results = model.process_batch(batch)
    # Faster than one-by-one
```

#### Caching
```python
# Cache model on GPU between requests
from functools import lru_cache

@lru_cache(maxsize=1)
def get_model():
    model = AutoModel.from_pretrained(...)
    model.eval()
    return model.to('cuda')

# Or use context manager
class ModelCache:
    def __init__(self):
        self.model = None
    
    def __enter__(self):
        if self.model is None:
            self.model = load_model()
        return self.model
    
    def __exit__(self, *args):
        pass  # Keep model in memory
```

#### Pruning
```python
# Remove less important weights
from transformers import AutoModelForCausalLM
from peft import prune_model

model = AutoModelForCausalLM.from_pretrained(...)

# Magnitude pruning
for module in model.modules():
    if hasattr(module, 'weight'):
        module.weight.data *= (torch.abs(module.weight.data) > threshold)
```

### 4.3 Inference Speed Profiling

```python
import time
import torch

def profile_inference(model, input_data, warmup=3, runs=10):
    # Warmup
    with torch.no_grad():
        for _ in range(warmup):
            _ = model(input_data)
    
    # Timing
    torch.cuda.synchronize() if torch.cuda.is_available() else None
    start = time.perf_counter()
    
    with torch.no_grad():
        for _ in range(runs):
            _ = model(input_data)
    
    torch.cuda.synchronize() if torch.cuda.is_available() else None
    elapsed = time.perf_counter() - start
    
    print(f"Average latency: {elapsed/runs*1000:.2f}ms")
    print(f"Throughput: {runs*batch_size/(elapsed):.2f} samples/sec")

# Usage
profile_inference(model, sample_image, warmup=3, runs=10)
```

## 5. Benchmark & Evaluation

### 5.1 Accuracy Evaluation

```python
from sklearn.metrics import accuracy_score, precision_recall_fscore_support

# Benchmark on property dataset
benchmark_data = [
    {
        "image": "interior.jpg",
        "ground_truth": {
            "condition": "good",
            "style": "modern",
            "features": ["hardwood_floors", "natural_light"]
        }
    },
    # ... more examples
]

predictions = []
ground_truths = []

for item in benchmark_data:
    image = Image.open(item["image"])
    prompt = "Describe the condition, style, and key features of this property interior."
    pred = model(image, prompt)
    predictions.append(pred)
    ground_truths.append(item["ground_truth"])

# Score
accuracy = calculate_semantic_similarity(predictions, ground_truths)
print(f"Accuracy: {accuracy:.2%}")
```

### 5.2 Speed Benchmark

```bash
# Using benchmark script
python benchmarks/speed_test.py \
  --model llama-3-2-vision:13b-instruct-q4_K_M \
  --images_dir ./test_images \
  --batch_sizes 1 2 4 8

# Output
Model: llama-3-2-vision:13b-instruct-q4_K_M
Batch Size 1: 245.3ms/image
Batch Size 2: 134.5ms/image
Batch Size 4: 78.2ms/image
```

### 5.3 Memory Benchmark

```bash
# Monitor GPU memory during inference
nvidia-smi --query-gpu=memory.used --format=csv,noheader -lms 100
```

## 6. Real-Estate Specific Optimization

### 6.1 Custom Fine-Tuning for Property Analysis

```python
# Training data structure
training_data = [
    {
        "image": "property_1.jpg",
        "question": "What is the condition of this property?",
        "answer": "The property appears to be in good condition with modern finishes and well-maintained spaces."
    },
    # ... 1000+ examples
]

# Fine-tune model
model = fine_tune_model(
    base_model="llama-3-2-vision:13b",
    training_data=training_data,
    epochs=3,
    learning_rate=2e-5
)
```

### 6.2 Prompt Engineering for Consistency

```python
SYSTEM_PROMPT = """You are a professional real estate property analyzer. 
Analyze property photos and provide structured assessments in JSON format.

For each image, provide:
- condition: "excellent" | "good" | "fair" | "poor"
- style: "modern" | "contemporary" | "traditional" | "colonial" | "other"
- features: list of observed features
- estimated_value_impact: "positive" | "neutral" | "negative"
- confidence: 0-100
"""

def analyze_property_image(image_path):
    image = Image.open(image_path)
    prompt = f"{SYSTEM_PROMPT}\n\nAnalyze this image and respond with valid JSON:"
    response = model.generate(image, prompt, max_new_tokens=512)
    return json.loads(response)
```

### 6.3 Batch Processing Pipeline

```python
from queue import Queue
from threading import Thread
import concurrent.futures

class PropertyAnalysisPipeline:
    def __init__(self, model, batch_size=4, num_workers=2):
        self.model = model
        self.batch_size = batch_size
        self.queue = Queue(maxsize=100)
        
        # Start worker threads
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=num_workers)
        for _ in range(num_workers):
            self.executor.submit(self._worker)
    
    def _worker(self):
        while True:
            batch = []
            for _ in range(self.batch_size):
                try:
                    batch.append(self.queue.get(timeout=5))
                except:
                    break
            
            if batch:
                results = self.model.batch_analyze(batch)
                for item, result in zip(batch, results):
                    item['callback'](result)
    
    def submit(self, property_id, image_path, callback):
        self.queue.put({
            'property_id': property_id,
            'image_path': image_path,
            'callback': callback
        })
```

## 7. Troubleshooting

### 7.1 Out of Memory
```
Solution 1: Reduce batch size
Solution 2: Use smaller model (Moondream vs Llama-3)
Solution 3: Enable INT4 quantization
Solution 4: Enable GPU offloading to CPU
Solution 5: Add second GPU with torch.nn.DataParallel
```

### 7.2 Slow Inference
```
Solution 1: Enable batching
Solution 2: Use model quantization (INT4)
Solution 3: Reduce context window (num_ctx)
Solution 4: Use faster model (Moondream)
Solution 5: Profile with nvidia-smi to find bottleneck
```

### 7.3 Accuracy Degradation
```
Solution 1: Check quantization bit width (try INT8 instead of INT4)
Solution 2: Validate calibration data quality
Solution 3: Fine-tune on property-specific data
Solution 4: Increase prompt clarity and structure
```

## 8. References

- [GPTQ: Accurate Post-Training Quantization for Generative Pre-trained Transformers](https://arxiv.org/abs/2210.17323)
- [AWQ: Activation-aware Weight Quantization for LLM Compression and Acceleration](https://arxiv.org/abs/2306.00978)
- [ONNX Runtime Performance Tuning](https://onnxruntime.ai/docs/performance/)
- [Ollama Model Library](https://ollama.ai/library)
- [Hugging Face Model Hub](https://huggingface.co/models)
