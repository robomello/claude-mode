.PHONY: check test scrub shellcheck-syntax pycompile unittest

check: shellcheck-syntax pycompile unittest scrub

shellcheck-syntax:
	@echo "== syntax-check scripts, dispatched on shebang =="
	@status=0; \
	for f in bin/* install.sh uninstall.sh; do \
		[ -f "$$f" ] || continue; \
		shebang="$$(head -n1 "$$f")"; \
		case "$$shebang" in \
			*python*) \
				continue ;; \
			*bash*) \
				echo "-- $$f (bash -n)"; \
				bash -n "$$f" || status=1 ;; \
			*sh*) \
				echo "-- $$f (sh -n)"; \
				sh -n "$$f" || status=1 ;; \
			*) \
				echo "-- $$f (no recognized shebang, skipping)" ;; \
		esac; \
	done; \
	exit $$status

pycompile:
	@echo "== python3 -m compileall lib bin =="
	python3 -m compileall -q lib bin

unittest:
	@echo "== python3 -m unittest discover -s tests =="
	python3 -m unittest discover -s tests -v

test: unittest

scrub:
	@echo "== scrubbing worktree for site-specific / secret content =="
	@hits=$$(grep -rInE --exclude-dir=.git --exclude=scrub-patterns.txt \
		-f scripts/scrub-patterns.txt \
		. || true); \
	if [ -n "$$hits" ]; then \
		echo "$$hits"; \
		echo; \
		echo "scrub: FAILED - site-specific values or secrets found in worktree (see matches above)"; \
		exit 1; \
	else \
		echo "scrub: clean"; \
	fi
