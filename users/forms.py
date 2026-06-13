from django import forms
from .models import AdminSettings

# forms.py
class CandidateForm(forms.Form):
    name = forms.CharField(max_length=100)
    email = forms.EmailField(widget=forms.EmailInput(attrs={'placeholder': 'enter valid email to send result'}))
    job_description = forms.CharField(widget=forms.Textarea(attrs={'placeholder': 'Example :Python Developer'}))
    question_level = forms.ChoiceField(choices=[
        ('Easy', 'Easy'),
        ('Medium', 'Medium'),
        ('Hard', 'Hard')
    ], initial='Easy')


class AnswerForm(forms.Form):
    answer = forms.CharField(widget=forms.Textarea)


class AdminSettingsForm(forms.ModelForm):
    class Meta:
        model = AdminSettings
        fields = ['difficulty_level', 'number_of_questions', 'question_type', 'interview_date', 'duration', 'evaluation_weightage', 'enable_emotion_analysis', 'enable_voice_interview']
        widgets = {
            'interview_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'evaluation_weightage': forms.Textarea(attrs={'placeholder': '{"accuracy": 0.4, "fluency": 0.3, "emotion_stability": 0.2, "eye_contact": 0.1}'}),
        }


class UserLoginForm(forms.Form):
    login_input = forms.CharField(label='Email or Mobile', max_length=100)
    password = forms.CharField(widget=forms.PasswordInput)


class OTPLoginForm(forms.Form):
    email = forms.EmailField()
    otp = forms.CharField(max_length=6)


class ForgotPasswordForm(forms.Form):
    email = forms.EmailField()


class ResetPasswordForm(forms.Form):
    new_password = forms.CharField(widget=forms.PasswordInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput)
