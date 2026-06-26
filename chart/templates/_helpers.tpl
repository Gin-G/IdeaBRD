{{- define "ideabrd.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ideabrd.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "ideabrd.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "ideabrd.labels" -}}
app.kubernetes.io/name: {{ include "ideabrd.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "ideabrd.imageTag" -}}
{{- default .Chart.AppVersion .Values.image.tag -}}
{{- end -}}

{{- define "ideabrd.backendImage" -}}
{{- printf "%s/%s:%s" .Values.image.registry .Values.backend.image (include "ideabrd.imageTag" .) -}}
{{- end -}}

{{- define "ideabrd.frontendImage" -}}
{{- printf "%s/%s:%s" .Values.image.registry .Values.frontend.image (include "ideabrd.imageTag" .) -}}
{{- end -}}

{{- define "ideabrd.dbClusterName" -}}
{{- printf "%s-db" (include "ideabrd.fullname" .) -}}
{{- end -}}

{{/* Name of the Secret holding the app config secrets. */}}
{{- define "ideabrd.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "ideabrd.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/* Public URL, derived from ingress host when not set explicitly. */}}
{{- define "ideabrd.publicUrl" -}}
{{- if .Values.config.publicUrl -}}
{{- .Values.config.publicUrl -}}
{{- else if .Values.ingress.tls.enabled -}}
{{- printf "https://%s" .Values.ingress.host -}}
{{- else -}}
{{- printf "http://%s" .Values.ingress.host -}}
{{- end -}}
{{- end -}}
