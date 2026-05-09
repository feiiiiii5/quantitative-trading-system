package main

import (
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

func requestIDMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		requestID := c.GetHeader("X-Request-ID")
		if requestID == "" {
			requestID = uuid.New().String()[:16]
		}
		c.Set("request_id", requestID)
		c.Header("X-Request-ID", requestID)
		c.Next()
	}
}

func timingMiddleware(logger interface{ Infow(msg string, keysAndValues ...interface{}) }) gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		elapsed := time.Since(start)
		if elapsed > 2*time.Second {
			logger.Infow("slow_request",
				"path", c.Request.URL.Path,
				"elapsed_ms", elapsed.Milliseconds(),
				"status", c.Writer.Status(),
			)
		} else if elapsed > 500*time.Millisecond {
			logger.Infow("medium_request",
				"path", c.Request.URL.Path,
				"elapsed_ms", elapsed.Milliseconds(),
			)
		}
	}
}

func rateLimitMiddleware(perMinute int) gin.HandlerFunc {
	type client struct {
		count   int
		resetAt time.Time
	}
	clients := make(map[string]*client)
	return func(c *gin.Context) {
		ip := c.ClientIP()
		now := time.Now()
		cl, exists := clients[ip]
		if !exists || now.After(cl.resetAt) {
			cl = &client{count: 0, resetAt: now.Add(time.Minute)}
			clients[ip] = cl
		}
		cl.count++
		if cl.count > perMinute {
			c.JSON(http.StatusTooManyRequests, gin.H{
				"success": false,
				"error":   "Rate limit exceeded",
			})
			c.Abort()
			return
		}
		c.Next()
	}
}

func securityHeadersMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("X-Content-Type-Options", "nosniff")
		c.Header("X-Frame-Options", "DENY")
		c.Header("X-XSS-Protection", "1; mode=block")
		c.Header("Referrer-Policy", "strict-origin-when-cross-origin")
		c.Header("Cache-Control", "no-store")
		c.Next()
	}
}
