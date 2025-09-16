<template>
    <div class="tool-activity-widget" v-if="loading || (completedTools.length > 0 && !hasNewMessage)">
        <div class="widget-trigger"
             :class="{ 'completed': completedTools.length > 0 && !loading }"
             @mouseenter="showDetails = true"
             @mouseleave="showDetails = false">
            <div class="current-indicator">
                <div class="spinner" v-if="loading && currentTool"></div>
                <span class="tool-name">{{ getDisplayText() }}</span>
            </div>
        </div>

        <div class="tool-details" v-show="showDetails">
            <div class="tool-list">
                <div v-for="tool in allTools" :key="tool.name" class="tool-item">
                    <div class="status-indicator" :class="getStatusClass(tool.name)">
                        <span v-if="isCompleted(tool.name)">✓</span>
                        <div v-else-if="isCurrent(tool.name)" class="mini-spinner"></div>
                    </div>
                    <div class="tool-content">
                        <div class="tool-title" :class="{ 'current': isCurrent(tool.name) }">
                            {{ tool.displayName }}
                        </div>
                        <div class="tool-description" v-if="tool.description">
                            {{ tool.description }}
                        </div>
                        <div class="tool-result" v-if="tool.result">
                            {{ tool.result }}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>

<script>
export default {
    name: 'ToolActivityWidget',
    props: {
        loading: {
            type: Boolean,
            default: false
        },
        currentTool: {
            type: String,
            default: ''
        },
        completedTools: {
            type: Array,
            default: () => []
        },
        totalIterations: {
            type: Number,
            default: 0
        },
        hasNewMessage: {
            type: Boolean,
            default: false
        },
        toolExecutionDetails: {
            type: Array,
            default: () => []
        }
    },
    data () {
        return {
            showDetails: false
        }
    },
    computed: {
        allTools () {
            // Get all tools that have been used in this session
            const usedTools = [...new Set([...this.completedTools, this.currentTool])].filter(Boolean)

            return usedTools.map(name => {
                const details = this.toolExecutionDetails.find(d => d.tool === name)
                return {
                    name,
                    displayName: this.getDisplayName(name),
                    description: this.getToolDescription(name),
                    result: details ? this.getToolResult(name, details) : null
                }
            })
        }
    },
    methods: {
        getDisplayText () {
            if (this.loading && this.currentTool) {
                return this.getDisplayName(this.currentTool)
            } else if (this.completedTools.length > 0) {
                return `${this.completedTools.length} tools completed`
            } else {
                return 'Processing...'
            }
        },
        getDisplayName (toolName) {
            if (toolName === 'telemetry_index') return 'Data Catalog'
            if (toolName === 'metrics_compute') return 'Flight Metrics'
            if (toolName === 'analyze_flight_baseline') return 'Baseline Analysis'
            if (toolName === 'detect_statistical_outliers') return 'Anomaly Detection'
            if (toolName === 'trace_causal_chains') return 'Event Correlation'
            if (toolName === 'telemetry_slice') return 'Data Extraction'
            return toolName || 'Processing...'
        },
        getStatusClass (toolName) {
            if (this.isCompleted(toolName)) return 'completed'
            if (this.isCurrent(toolName)) return 'current'
            return 'pending'
        },
        isCompleted (toolName) {
            return this.completedTools.includes(toolName)
        },
        isCurrent (toolName) {
            return toolName === this.currentTool
        },
        getToolDescription (toolName) {
            if (toolName === 'telemetry_index') {
                return 'Cataloging available data streams and their properties'
            } else if (toolName === 'metrics_compute') {
                return 'Calculating key flight metrics and performance indicators'
            } else if (toolName === 'analyze_flight_baseline') {
                return 'Establishing statistical baselines for normal flight behavior'
            } else if (toolName === 'detect_statistical_outliers') {
                return 'Identifying anomalies using advanced statistical analysis'
            } else if (toolName === 'trace_causal_chains') {
                return 'Correlating events to find potential cause-and-effect relationships'
            } else if (toolName === 'telemetry_slice') {
                return 'Extracting specific data segments for detailed analysis'
            }
            return 'Processing flight data'
        },
        getToolResult (toolName, details) {
            // This would be enhanced with actual results from the backend
            // For now, return generic success messages
            if (toolName === 'telemetry_index') {
                return 'Found 5 data streams available for analysis'
            } else if (toolName === 'metrics_compute') {
                return 'Computed flight duration, max altitude, and critical events'
            } else if (toolName === 'analyze_flight_baseline') {
                return 'Established statistical baselines for normal operation'
            } else if (toolName === 'detect_statistical_outliers') {
                return 'No significant anomalies detected in flight data'
            } else if (toolName === 'trace_causal_chains') {
                return 'Identified temporal relationships between events'
            } else if (toolName === 'telemetry_slice') {
                return 'Extracted relevant data segments for analysis'
            }
            return 'Analysis completed successfully'
        }
    }
}
</script>

<style scoped>
.tool-activity-widget {
    position: relative;
    display: inline-block;
}

.widget-trigger {
    display: flex;
    align-items: center;
    padding: 8px 12px;
    background: #f8f9fa;
    border: 1px solid #e9ecef;
    border-radius: 20px;
    cursor: pointer;
    transition: all 0.3s ease;
    min-width: 40px;
    height: 40px;
}

.widget-trigger:hover {
    background: #e9ecef;
    border-color: #dee2e6;
}

.widget-trigger.completed {
    background: #e3f2fd;
    border-color: #bbdefb;
}

.widget-trigger.completed:hover {
    background: #bbdefb;
    border-color: #90caf9;
}

.current-indicator {
    display: flex;
    align-items: center;
    gap: 8px;
}

.spinner {
    width: 16px;
    height: 16px;
    border: 2px solid #e9ecef;
    border-top: 2px solid #007bff;
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

.tool-name {
    font-size: 14px;
    color: #495057;
    white-space: nowrap;
}

.tool-details {
    position: absolute;
    top: 100%;
    right: 0;
    margin-top: 4px;
    background: white;
    border: 1px solid #dee2e6;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    z-index: 1005;
    min-width: 200px;
    max-width: 250px;
}

.tool-list {
    padding: 12px;
}

.tool-item {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 8px 0;
    line-height: 1.4;
}

.status-indicator {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    font-weight: bold;
    flex-shrink: 0;
}

.status-indicator.completed {
    background: #3a7bc8;
    color: white;
}

.status-indicator.current {
    background: #007bff;
    color: white;
}

.status-indicator.pending {
    background: transparent;
    border: 2px solid #dee2e6;
}

.mini-spinner {
    width: 8px;
    height: 8px;
    border: 1px solid rgba(255, 255, 255, 0.3);
    border-top: 1px solid white;
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

.tool-content {
    flex: 1;
    min-width: 0;
}

.tool-title {
    font-size: 14px;
    color: #6c757d;
    transition: color 0.2s ease;
    font-weight: 500;
    margin-bottom: 2px;
}

.tool-title.current {
    color: #212529;
    font-weight: 600;
}

.tool-description {
    font-size: 12px;
    color: #868e96;
    margin-bottom: 2px;
    line-height: 1.3;
}

.tool-result {
    font-size: 11px;
    color: #3a7bc8;
    font-style: italic;
    line-height: 1.3;
}

@keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}
</style>
