# Monitoring stage. Build from the repo root:
#   docker build -f stages/monitor/Dockerfile -t ml-monitor:latest .
#
# Evidently lives ONLY here. It pulls in plotly and around 500MB, and
# ml-base is the parent of six stage images plus serving - none of which
# ever compute drift. Putting it in the base would make every one of them
# carry the weight.
FROM ml-base:latest

RUN pip install --no-cache-dir "evidently>=0.7,<0.8"

COPY stages/monitor/main.py /app/main.py

WORKDIR /app
CMD ["python", "main.py"]
