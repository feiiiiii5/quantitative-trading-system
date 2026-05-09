module github.com/quantcore/api-gateway

go 1.22

require (
	github.com/gin-gonic/gin v1.10.0
	github.com/redis/go-redis/v9 v9.7.0
	go.opentelemetry.io/otel v1.29.0
	go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc v1.29.0
	go.opentelemetry.io/otel/sdk v1.29.0
	go.uber.org/zap v1.27.0
	google.golang.org/grpc v1.66.0
	google.golang.org/protobuf v1.34.2
)
