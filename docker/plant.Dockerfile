# Plant simulator image: runs the Modbus TCP process front-end.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
# Only the simulator's runtime deps are needed in this image.
RUN pip install --no-cache-dir pymodbus==3.11.3
COPY sim/ ./sim/
EXPOSE 5020
CMD ["python", "-m", "sim.modbus_server", "--host", "0.0.0.0", "--port", "5020"]
