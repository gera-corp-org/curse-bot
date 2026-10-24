{{- define "curse-bot.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "curse-bot.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "curse-bot.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{ include "curse-bot.selectorLabels" . }}
app.kubernetes.io/version: {{ .Values.image.tag | default .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "curse-bot.selectorLabels" -}}
app.kubernetes.io/name: {{ include "curse-bot.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "curse-bot.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "curse-bot.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "curse-bot.image" -}}
{{- if .Values.image.digest }}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest }}
{{- else }}
{{- printf "%s:%s" .Values.image.repository (.Values.image.tag | default .Chart.AppVersion) }}
{{- end }}
{{- end }}

{{/* Аннотации для bank-vaults vault-secrets-webhook и vault-secrets-reloader. */}}
{{- define "curse-bot.vaultAnnotations" -}}
{{- with .Values.vault }}
{{- if .enabled }}
{{- with .addr }}
vault.security.banzaicloud.io/vault-addr: {{ . | quote }}
{{- end }}
{{- with .role }}
vault.security.banzaicloud.io/vault-role: {{ . | quote }}
{{- end }}
{{- with .authPath }}
vault.security.banzaicloud.io/vault-path: {{ . | quote }}
{{- end }}
{{- with .skipVerify }}
vault.security.banzaicloud.io/vault-skip-verify: {{ . | quote }}
{{- end }}
{{- if .reloadOnSecretChange }}
secrets-reloader.security.bank-vaults.io/reload-on-secret-change: "true"
{{- end }}
{{- with .annotations }}
{{ toYaml . }}
{{- end }}
{{- end }}
{{- end }}
{{- end }}
