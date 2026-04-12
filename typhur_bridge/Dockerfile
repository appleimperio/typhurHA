ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache python3 py3-pip py3-requests openssl && \
    pip3 install paho-mqtt --break-system-packages 2>/dev/null || \
    pip3 install paho-mqtt

WORKDIR /app
COPY run.py .

CMD ["python3", "/app/run.py"]
