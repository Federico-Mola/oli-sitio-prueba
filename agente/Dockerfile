FROM python:3.12-alpine
RUN apk add --no-cache tzdata
WORKDIR /app
COPY server.py ./
COPY config ./config
COPY web ./web
RUN addgroup -S oli && adduser -S -G oli -u 10001 oli && mkdir /state && chown oli:oli /state
USER oli
ENV OLI_STATE=/state OLI_BIND=0.0.0.0 OLI_PORT=8094
EXPOSE 8094
CMD ["python", "server.py"]
