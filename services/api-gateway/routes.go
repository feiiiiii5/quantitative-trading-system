package main

import (
	"context"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

type ServiceRegistry struct {
	marketDataConn *grpc.ClientConn
	orderConn      *grpc.ClientConn
	riskConn       *grpc.ClientConn
	strategyConn   *grpc.ClientConn
	portfolioConn  *grpc.ClientConn
}

func NewServiceRegistry(cfg *Config) (*ServiceRegistry, error) {
	reg := &ServiceRegistry{}
	var err error

	reg.marketDataConn, err = grpc.Dial(cfg.MarketDataAddr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithBlock(),
		grpc.WithTimeout(5*time.Second),
	)
	if err != nil {
		return nil, err
	}

	return reg, nil
}

func (r *ServiceRegistry) Close() {
	if r.marketDataConn != nil {
		r.marketDataConn.Close()
	}
	if r.orderConn != nil {
		r.orderConn.Close()
	}
	if r.riskConn != nil {
		r.riskConn.Close()
	}
	if r.strategyConn != nil {
		r.strategyConn.Close()
	}
	if r.portfolioConn != nil {
		r.portfolioConn.Close()
	}
}

func registerRoutes(r *gin.Engine, cfg *Config, logger interface{ Infow(msg string, keysAndValues ...interface{}) }) {
	r.GET("/api/health", healthHandler(cfg))

	api := r.Group("/api")
	{
		api.GET("/market/realtime", proxyMarketRealtime(cfg))
		api.GET("/market/history", proxyMarketHistory(cfg))
		api.GET("/sse/realtime", sseRealtimeHandler(cfg))

		api.POST("/orders/submit", proxyOrderSubmit(cfg))
		api.POST("/orders/cancel", proxyOrderCancel(cfg))
		api.GET("/orders/status", proxyOrderStatus(cfg))

		api.POST("/risk/pre-trade", proxyRiskPreTrade(cfg))
		api.GET("/risk/metrics", proxyRiskMetrics(cfg))

		api.POST("/strategy/backtest", proxyStrategyBacktest(cfg))
		api.POST("/strategy/deploy", proxyStrategyDeploy(cfg))
		api.GET("/strategy/list", proxyStrategyList(cfg))

		api.GET("/portfolio", proxyPortfolio(cfg))
		api.GET("/portfolio/positions", proxyPositions(cfg))
		api.GET("/portfolio/pnl", proxyPnL(cfg))
	}
}

func healthHandler(cfg *Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		checks := gin.H{}
		allOK := true

		ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
		defer cancel()

		checks["market_data"] = checkGRPC(ctx, cfg.MarketDataAddr)
		checks["order_engine"] = checkGRPC(ctx, cfg.OrderAddr)
		checks["risk_engine"] = checkGRPC(ctx, cfg.RiskAddr)
		checks["strategy_engine"] = checkGRPC(ctx, cfg.StrategyAddr)
		checks["portfolio_engine"] = checkGRPC(ctx, cfg.PortfolioAddr)

		for _, v := range checks {
			if v != "ok" {
				allOK = false
				break
			}
		}

		status := "healthy"
		if !allOK {
			status = "degraded"
		}

		c.JSON(http.StatusOK, gin.H{
			"status":    status,
			"checks":    checks,
			"version":   "4.0.0",
			"timestamp": time.Now().Unix(),
		})
	}
}

func checkGRPC(ctx context.Context, addr string) string {
	conn, err := grpc.DialContext(ctx, addr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithBlock(),
	)
	if err != nil {
		return "unavailable"
	}
	conn.Close()
	return "ok"
}

func proxyMarketRealtime(cfg *Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"success": true, "data": "market_data_service_proxy"})
	}
}

func proxyMarketHistory(cfg *Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"success": true, "data": "market_data_history_proxy"})
	}
}

func sseRealtimeHandler(cfg *Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("Content-Type", "text/event-stream")
		c.Header("Cache-Control", "no-cache")
		c.Header("Connection", "keep-alive")
		c.Header("X-Accel-Buffering", "no")

		c.SSEvent("connected", "QuantCore SSE v4.0.0")
	}
}

func proxyOrderSubmit(cfg *Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"success": true, "data": "order_submit_proxy"})
	}
}

func proxyOrderCancel(cfg *Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"success": true, "data": "order_cancel_proxy"})
	}
}

func proxyOrderStatus(cfg *Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"success": true, "data": "order_status_proxy"})
	}
}

func proxyRiskPreTrade(cfg *Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"success": true, "data": "risk_pre_trade_proxy"})
	}
}

func proxyRiskMetrics(cfg *Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"success": true, "data": "risk_metrics_proxy"})
	}
}

func proxyStrategyBacktest(cfg *Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"success": true, "data": "strategy_backtest_proxy"})
	}
}

func proxyStrategyDeploy(cfg *Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"success": true, "data": "strategy_deploy_proxy"})
	}
}

func proxyStrategyList(cfg *Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"success": true, "data": "strategy_list_proxy"})
	}
}

func proxyPortfolio(cfg *Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"success": true, "data": "portfolio_proxy"})
	}
}

func proxyPositions(cfg *Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"success": true, "data": "positions_proxy"})
	}
}

func proxyPnL(cfg *Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"success": true, "data": "pnl_proxy"})
	}
}
