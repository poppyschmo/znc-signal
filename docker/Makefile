# This is only for pulling sources for the Docker build; GNU make only

# Note: changing this bunch via env vars only makes sense for inspection
# purposes; they're hard-coded in the Dockerfile, (no ARG overrides)
SRCDIR ?= src
SIGCLI_REV ?= 0.5.6
LIBMAT_REV ?= 0.8

SIGCLI_PKG = signal-cli-$(SIGCLI_REV)
SC_PKG_TAR = $(SIGCLI_PKG).tar.gz
SC_SRC_TAR = v$(SIGCLI_REV).tar.gz
LIBMAT_TAR = libmatthew-java-$(LIBMAT_REV).tar.gz

SIGCLI_BASE_URL = https://github.com/AsamK/signal-cli
LIBMAT_BASE_URL = http://www.matthew.ath.cx/

LIBMAT_SRC_URL = $(LIBMAT_BASE_URL)/projects/java/$(LIBMAT_TAR)
SIGCLI_PKG_URL = $(SIGCLI_BASE_URL)/releases/download/v$(SIGCLI_REV)/$(SC_PKG_TAR)
SIGCLI_SRC_URL = $(SIGCLI_BASE_URL)/archive/$(SC_SRC_TAR)

VPATH = $(SRCDIR)

all: org.asamk.Signal.conf $(SC_PKG_TAR) $(LIBMAT_TAR)
.PHONY: all

org.asamk.Signal.conf: $(SC_SRC_TAR)
	cd $(SRCDIR) && \
	tar -xf $(SC_SRC_TAR) --strip-components=2 \
		$(SIGCLI_PKG)/data/$@ && \
	touch $@

$(LIBMAT_TAR): | $(SRCDIR)
	cd $(SRCDIR) && \
	curl -LO $(LIBMAT_SRC_URL)

$(SC_PKG_TAR): | $(SRCDIR)
	cd $(SRCDIR) && \
	curl -LO $(SIGCLI_PKG_URL)

$(SC_SRC_TAR): | $(SRCDIR)
	cd $(SRCDIR) && \
	curl -LO $(SIGCLI_SRC_URL)

$(SRCDIR):
	@printf '\x1b[33;1m%s\x1b[m: %s\n' "Note" \
		"this only downloads files, it doesn't build the actual image" \
		"Warning" "no PGP signature verification is performed"
	mkdir -v $@
