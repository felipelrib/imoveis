ROCm / DirectML setup for AMD RX 7900 XT (expert notes)

1) ROCm (Linux preferred):
- ROCm support for RDNA3 is limited; check ROCm 6.x+ compatibility with your distribution.
- Use a supported Linux distro (Ubuntu LTS or RHEL/CentOS derivatives) and the latest ROCm release.
- Install ROCm, set HSA and HIP environment variables, and verify with rocminfo / rocblas tests.
- Use PyTorch built with ROCm (install via pip from PyTorch ROCm wheels) and ensure OpenCL/ROCm backend works for your VLM framework.

2) DirectML (Windows):
- For Windows, prefer DirectML-enabled runtimes (ONNX Runtime with DirectML, or TensorFlow-DirectML builds).
- Install latest GPU drivers from AMD with DirectML support.
- Use ONNX Runtime with DirectML provider to run quantized vision models. Example: pip install onnxruntime-directml

3) Model selection & quantization:
- Prefer FP16 or INT8 quantized models to fit in 20GB VRAM.
- Use tools like nn_pruning / ggml / awq / bitsandbytes alternatives where supported. On AMD, bitsandbytes is limited; prefer ONNX quantization.

4) Local VLM servers (Ollama / LM Studio / custom):
- Ollama currently supports NVIDIA more robustly; for AMD, run model via ONNX Runtime + DirectML or custom FastAPI wrapper around an optimized inference engine.
- Use smaller vision-language models (Qwen-2-VL-small, LLaVA-lite) for local GPU inference.

5) Resource management:
- Constrain worker concurrency to 1-2 when running GPU jobs; use GPU semaphore to avoid overcommit.
- Monitor GPU memory with tools: GPU-Z (Windows) or rocm-smi / radeontop (Linux).

6) Recommendations:
- Prefer Linux + ROCm for best throughput and driver compatibility.
- If staying on Windows, DirectML + ONNX Runtime is the practical route.
- Keep models quantized and use batching to improve throughput.
