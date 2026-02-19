import { useEffect, useRef } from 'react'
import { createChart, ColorType, LineStyle } from 'lightweight-charts'
import './EquityChart.css'

const CHART_COLORS = {
    background: '#111827',
    textColor: '#94a3b8',
    gridColor: '#1e2d42',
    equityLine: '#3b82f6',
    balanceLine: '#8b5cf6',
    drawdownArea: 'rgba(239, 68, 68, 0.3)',
}

// Color palette for indicators
const INDICATOR_COLORS = [
    '#22c55e',   // green
    '#f59e0b',   // amber
    '#06b6d4',   // cyan
    '#ec4899',   // pink
    '#a855f7',   // purple
    '#f97316',   // orange
]

export default function EquityChart({ results }) {
    const chartContainerRef = useRef(null)
    const chartRef = useRef(null)

    useEffect(() => {
        if (!results || !chartContainerRef.current) return

        // Clean up previous chart
        if (chartRef.current) {
            chartRef.current.remove()
            chartRef.current = null
        }

        const container = chartContainerRef.current
        const chart = createChart(container, {
            width: container.clientWidth,
            height: 380,
            layout: {
                background: { type: ColorType.Solid, color: CHART_COLORS.background },
                textColor: CHART_COLORS.textColor,
                fontFamily: "'Inter', sans-serif",
                fontSize: 11,
            },
            grid: {
                vertLines: { color: CHART_COLORS.gridColor },
                horzLines: { color: CHART_COLORS.gridColor },
            },
            rightPriceScale: {
                borderColor: CHART_COLORS.gridColor,
            },
            timeScale: {
                borderColor: CHART_COLORS.gridColor,
                timeVisible: true,
                secondsVisible: false,
            },
            crosshair: {
                vertLine: { color: 'rgba(59, 130, 246, 0.3)', style: LineStyle.Dashed },
                horzLine: { color: 'rgba(59, 130, 246, 0.3)', style: LineStyle.Dashed },
            },
        })

        chartRef.current = chart

        // Equity curve
        if (results.equity_curve?.length > 0) {
            const equitySeries = chart.addLineSeries({
                color: CHART_COLORS.equityLine,
                lineWidth: 2,
                title: 'Equity',
                priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
            })

            const equityData = results.equity_curve.map(p => ({
                time: p.time.includes('T') ? Math.floor(new Date(p.time).getTime() / 1000) : p.time,
                value: p.equity,
            }))

            equitySeries.setData(equityData)

            // Balance line
            const balanceSeries = chart.addLineSeries({
                color: CHART_COLORS.balanceLine,
                lineWidth: 1,
                lineStyle: LineStyle.Dashed,
                title: 'Balance',
                priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
            })

            const balanceData = results.equity_curve.map(p => ({
                time: p.time.includes('T') ? Math.floor(new Date(p.time).getTime() / 1000) : p.time,
                value: p.balance,
            }))

            balanceSeries.setData(balanceData)
        }

        // Fit content
        chart.timeScale().fitContent()

        // Handle resize
        const handleResize = () => {
            chart.applyOptions({ width: container.clientWidth })
        }
        window.addEventListener('resize', handleResize)

        return () => {
            window.removeEventListener('resize', handleResize)
            chart.remove()
            chartRef.current = null
        }
    }, [results])

    if (!results) return null

    return (
        <div className="equity-chart-container">
            <h3 className="chart-title">
                Equity Curve
                <span className="chart-legend">
                    <span className="legend-item">
                        <span className="legend-color" style={{ background: CHART_COLORS.equityLine }} />
                        Equity
                    </span>
                    <span className="legend-item">
                        <span className="legend-color" style={{ background: CHART_COLORS.balanceLine }} />
                        Balance
                    </span>
                </span>
            </h3>
            <div ref={chartContainerRef} className="chart-canvas" />
        </div>
    )
}
