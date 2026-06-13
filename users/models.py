from django.db import models
from django.utils import timezone

# models.py
class AdminSettings(models.Model):
    difficulty_level = models.CharField(max_length=20, default='Easy', choices=[
        ('Easy', 'Easy'),
        ('Medium', 'Medium'),
        ('Hard', 'Hard')
    ])
    number_of_questions = models.IntegerField(default=10)
    question_type = models.CharField(max_length=20, default='Descriptive', choices=[
        ('MCQ', 'MCQ'),
        ('Descriptive', 'Descriptive'),
        ('Coding', 'Coding'),
        ('Voice', 'Voice')
    ])
    interview_date = models.DateTimeField(default=timezone.now)
    duration = models.IntegerField(default=60)  # minutes
    evaluation_weightage = models.JSONField(default=dict)  # e.g. {'accuracy': 0.4, 'fluency': 0.3, ...}
    enable_emotion_analysis = models.BooleanField(default=True)
    enable_voice_interview = models.BooleanField(default=True)

class Interview(models.Model):
    candidate = models.OneToOneField('Candidate', on_delete=models.CASCADE)
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    total_score = models.FloatField(null=True, blank=True)
    confidence_level = models.FloatField(null=True, blank=True)
    final_decision = models.CharField(max_length=20, choices=[
        ('Pass', 'Pass'),
        ('Fail', 'Fail')
    ], null=True, blank=True)

class Questions(models.Model):
    interview = models.ForeignKey(Interview, on_delete=models.CASCADE)
    question_text = models.TextField()
    question_type = models.CharField(max_length=20, choices=[
        ('MCQ', 'MCQ'),
        ('Descriptive', 'Descriptive'),
        ('Coding', 'Coding'),
        ('Voice', 'Voice')
    ])
    correct_answer = models.TextField(blank=True, null=True)
    difficulty = models.CharField(max_length=20, choices=[
        ('Easy', 'Easy'),
        ('Medium', 'Medium'),
        ('Hard', 'Hard')
    ])

class Answers(models.Model):
    question = models.ForeignKey(Questions, on_delete=models.CASCADE)
    candidate_answer = models.TextField()
    score = models.FloatField(null=True, blank=True)
    explanation = models.TextField(blank=True, null=True)

class SpeechTranscripts(models.Model):
    answer = models.OneToOneField(Answers, on_delete=models.CASCADE)
    transcript = models.TextField()
    fluency_score = models.FloatField(null=True, blank=True)
    speech_accuracy = models.FloatField(null=True, blank=True)

class EmotionLogs(models.Model):
    interview = models.ForeignKey(Interview, on_delete=models.CASCADE)
    question = models.ForeignKey(Questions, on_delete=models.CASCADE, null=True, blank=True)
    timestamp = models.DateTimeField(default=timezone.now)
    emotion = models.CharField(max_length=50)  # e.g. Happy, Neutral, Nervous
    confidence = models.FloatField()

class PerformanceMetrics(models.Model):
    interview = models.OneToOneField(Interview, on_delete=models.CASCADE)
    accuracy_percentage = models.FloatField()
    confidence_level = models.FloatField()
    strengths = models.TextField()
    weak_areas = models.TextField()
    recommendation = models.TextField()
    eye_contact_percentage = models.FloatField(null=True, blank=True)
    speech_fluency_score = models.FloatField(null=True, blank=True)

class Candidate(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    job_description = models.TextField()
    interview_date = models.DateTimeField(default=timezone.now)
    question_level = models.CharField(max_length=20, default='Easy', choices=[
        ('Easy', 'Easy'),
        ('Medium', 'Medium'),
        ('Hard', 'Hard')
    ])

    def __str__(self):
        return self.name


class InterviewResponse(models.Model):  # Keeping for backward compatibility, but new structure uses above models
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE)
    question = models.TextField()
    answer = models.TextField()
    correct_answer = models.TextField(blank=True, null=True)
    score = models.IntegerField(null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    emotion = models.CharField(max_length=50, blank=True, null=True)


class RegisteredUser(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    mobile = models.CharField(max_length=15)
    password = models.CharField(max_length=100)  # store plain for demo; use hashing in prod!
    image = models.ImageField(upload_to='user_images/')
    is_active = models.BooleanField(default=False)

    def __str__(self):
        return self.name
