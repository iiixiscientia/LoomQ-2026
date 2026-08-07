FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# pyqpanda 依赖 libcurl.so.4
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcurl4 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/starter-kit
COPY requirements.txt requirements-spinq.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# spinqit 需要 antlr4-python3-runtime==4.9.2，跟 amazon-braket-default-simulator
# 强制要求的 4.13.2 互斥，没法装进同一个环境——单独建一个 venv 装 spinqit，
# src/backends/spinq_backend.py 通过 subprocess 调用它（见该文件顶部注释）。
RUN python3 -m venv spinq_env \
    && spinq_env/bin/pip install --no-cache-dir -r requirements-spinq.txt

COPY . .

CMD ["python", "evaluator.py", "--json-out", "/tmp/loomq-public-report.json"]
