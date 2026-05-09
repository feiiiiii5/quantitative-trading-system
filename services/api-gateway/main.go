package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
)

type Config struct {
	Port            string
	MarketDataAddr  string
	OrderAddr       string
	RiskAddr        string
	StrategyAddr    string
	PortfolioAddr   string
	RedisAddr       string
	JWTSecret       string
	RateLimitPerMin int
}

func LoadConfig() *Config {
	return &Config{
		Port:            getEnv("GATEWAY_PORT", "8080"),
		MarketDataAddr:  getEnv("MARKET_DATA_ADDR", "localhost:50051"),
		OrderAddr:       getEnv("ORDER_ENGINE_ADDR", "localhost:50052"),
		RiskAddr:        getEnv("RISK_ENGINE_ADDR", "localhost:50053"),
		StrategyAddr:    getEnv("STRATEGY_ENGINE_ADDR", "localhost:50054"),
		PortfolioAddr:   getEnv("PORTFOLIO_ENGINE_ADDR", "localhost:50055"),
		RedisAddr:       getEnv("REDIS_ADDR", "localhost:6379"),
		JWTSecret:       getEnv("JWT_SECRET", ""),
		RateLimitPerMin: getEnvInt("RATE_LIMIT_PER_MIN", 600),
	}
}

func main() {
	logger, _ := zap.NewProduction()
	defer logger.Sync()
	sugar := logger.Sugar()

	cfg := LoadConfig()
	sugar.Infow("Starting QuantCore API Gateway",
		"port", cfg.Port,
		"market_data", cfg.MarketDataAddr,
	)

	if os.Getenv("GIN_MODE") == "" {
		gin.SetMode(gin.ReleaseMode)
	}

	router := gin.New()
	router.Use(gin.Recovery())
	router.Use(requestIDMiddleware())
	router.Use(timingMiddleware(sugar))
	router.Use(rateLimitMiddleware(cfg.RateLimitPerMin))
	router.Use(securityHeadersMiddleware())

	registerRoutes(router, cfg, sugar)

	srv := &http.Server{
		Addr:         ":" + cfg.Port,
		Handler:      router,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	go func() {
		sugar.Infow("Gateway listening", "addr", srv.Addr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			sugar.Fatalw("Listen failed", "error", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	sugar.Info("Shutting down gateway...")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		sugar.Fatalw("Forced shutdown", "error", err)
	}
	sugar.Info("Gateway exited")
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func getEnvInt(key string, fallback int) int {
	if v := os.Getenv(key); v != "" {
		var i int
		if _, err := time.ParseDuration(v); err == nil {
			return i
		}
		log.Printf("invalid int env %s=%s, using default %d", key, v, fallback)
	}
	return fallback
}
