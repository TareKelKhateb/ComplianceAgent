import re

class TextFormatter:
    """
    Final cleaning layer before chunking.
    Ensures legal articles are consistently tagged regardless of OCR source.
    """
    def __init__(self):
        # Pattern to catch Arabic articles headers 
        self.article_pattern = re.compile(
            r'^(مادة|المادة)'
            r'\s*[\(\（]?\s*'
            r'(\d+|[٠-٩]+|[أ-ي]+)'
            r'\s*[\)\）]?\s*:?\s*$',
            re.MULTILINE
        )

    def clean_and_format(self, text: str) -> str:
        """
        Standardizes the output for downstream semantic analysis.
        """
        lines = text.split('\n')
        processed_lines = []

        for line in lines:
            stripped = line.strip()
            if self.article_pattern.match(stripped):
                # We enforce a clean Markdown H3 for all article headers
                processed_lines.append(f"### {stripped}")
            else:
                processed_lines.append(stripped)

        return "\n".join(processed_lines)