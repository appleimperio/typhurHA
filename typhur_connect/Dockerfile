ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache openssl && \
    pip3 install --no-cache-dir requests paho-mqtt

WORKDIR /app
COPY run.py .

CMD ["python3", "/app/run.py"]
