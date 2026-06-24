import os
import smtplib
import logging
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("EmailSender")

def send_review_email(review_url: str) -> bool:
    """
    Send an email notification to the user with the review URL.
    
    If SMTP variables are not configured in environment, it logs the email to
    logs/email_notifications.log and prints it to the console.
    """
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = os.getenv("SMTP_PORT", "587")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_SENDER", smtp_user or "compliance-agent@local.com")
    receiver = os.getenv("EMAIL_RECEIVER", "tarekelkhateb31@gmail.com")
    
    subject = "Action Required: Compliance Metadata Review Session"
    body = (
        f"Hello,\n\n"
        f"A new batch of compliance documents has been scraped and is ready for your review.\n"
        f"Please click the link below to review, adjust, and approve the metadata:\n\n"
        f"{review_url}\n\n"
        f"Best regards,\n"
        f"Compliance Agent System"
    )
    
    # 1. Console & file log fallback
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_dir = os.path.join(project_root, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "email_notifications.log")
    
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(f"--- EMAIL TO: {receiver} ---\nSubject: {subject}\nBody:\n{body}\n---------------------\n\n")
    except Exception as e:
        logger.error("Failed to write mock email to file: %s", e)
        
    logger.info("=============================================================")
    logger.info("EMAIL NOTIFICATION TO: %s", receiver)
    logger.info("Subject: %s", subject)
    logger.info("Review URL: %s", review_url)
    logger.info("Saved copy of email to %s", os.path.basename(log_file))
    logger.info("=============================================================")

    # 2. Real SMTP sending
    if not smtp_server or not smtp_user or not smtp_pass:
        logger.warning("SMTP server or credentials (SMTP_USER/SMTP_PASSWORD) not configured in .env. Real email sending skipped (logged to file).")
        return True
        
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = receiver
        
        logger.info("Attempting to send email via SMTP (%s:%s)...", smtp_server, smtp_port)
        with smtplib.SMTP(smtp_server, int(smtp_port), timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(sender, [receiver], msg.as_string())
        logger.info("Successfully sent email to %s via SMTP server %s", receiver, smtp_server)
        return True
    except Exception as exc:
        logger.error("Failed to send email via SMTP server: %s. Real email could not be sent, but copy was saved to file log.", exc)
        return False
